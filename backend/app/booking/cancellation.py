"""Booking cancellation and the waitlist assignment it triggers.

TRANSACTION BOUNDARY: `cancel_booking` performs steps (a) through (h) with no
commit and no rollback of its own. The router commits once, after it returns,
so the whole unit -- cancelling the booking, releasing the seats, creating
offers, re-claiming the seats for those offers, and staging both emails --
lands atomically.

That is not a stylistic choice. If offer creation and seat re-claim landed in
separate transactions there would be a window in which the cancelled seats read
as 'available' on the seat map while an offer email is already in flight, and a
browsing customer could take a seat that has been promised to someone else. The
window is invisible in testing and shows up under load as a double sale.
"""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking import assignment
from app.booking.service import _load_show_context
from app.booking.sql import RELEASE_GROUP
from app.core.config import settings
from app.core.errors import conflict, forbidden, not_found
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    Outbox,
    Seat,
    SeatCategory,
    UserAccount,
)
from app.schemas.waitlist import CancelResponse, CancelledOffer


async def load_own_booking(
    session: AsyncSession, reference: str, user: UserAccount
) -> Booking:
    booking = await session.scalar(
        select(Booking).where(Booking.reference == reference)
    )
    if booking is None:
        raise not_found("No such booking.")
    if booking.user_id != user.id:
        raise forbidden("That booking is not yours.")
    return booking


async def cancel_booking(
    session: AsyncSession, user: UserAccount, reference: str
) -> CancelResponse:
    """Cancel, release, and hand the seats to the waitlist. Caller commits."""
    booking = await load_own_booking(session, reference, user)

    if booking.status is BookingStatus.CANCELLED:
        # Idempotent-safe: report the existing cancellation rather than
        # releasing the same seats a second time.
        return await _describe(session, booking, [])

    # Cutoff measured by the database clock, never the application's.
    too_late = await session.scalar(
        text(
            "SELECT now() > starts_at - make_interval(mins => :cutoff)"
            " FROM show WHERE id = :sid"
        ),
        {"cutoff": settings.cancellation_cutoff_minutes, "sid": booking.show_id},
    )
    if too_late:
        raise conflict(
            "This booking can no longer be cancelled: the cutoff has passed.",
            {"cutoff_minutes": settings.cancellation_cutoff_minutes},
        )

    # (a) the booking itself.
    #
    # Written as one statement rather than by assigning to the ORM object: the
    # session runs with autoflush disabled, so a pending attribute change would
    # be silently discarded by the refresh in _describe below, releasing the
    # seats while leaving the booking 'confirmed'.
    await session.execute(
        text(
            "UPDATE booking SET status = 'cancelled', cancelled_at = now()"
            " WHERE id = :id"
        ),
        {"id": booking.id},
    )

    # (b) release every claim in the group -- they are 'booked', not 'held'
    freed = (
        (await session.execute(RELEASE_GROUP, {"group": str(booking.hold_group_id)}))
        .scalars()
        .all()
    )

    show, event, screen, venue = await _load_show_context(session, booking.show_id)

    # (c)-(g) The shared cascade. Identical code to the one the sweeper runs
    # when an offer lapses -- one implementation, two callers -- and it runs
    # inside THIS transaction, so the seats are never visible as available
    # between being released and being re-claimed for an offer.
    outcomes = await assignment.assign_freed_seats(session, show.id, list(freed))

    described = [
        CancelledOffer(
            offer_id=o.offer_id,
            entry_id=o.entry_id,
            seat_ids=o.seat_ids,
            seat_labels=o.seat_labels,
            category_name=o.category_name,
            expires_at=o.expires_at,
        )
        for o in outcomes
    ]

    # (h) tell the customer
    booked_seats = (
        await session.execute(
            select(BookingSeat, Seat, SeatCategory)
            .join(Seat, Seat.id == BookingSeat.seat_id)
            .join(SeatCategory, SeatCategory.id == BookingSeat.category_id)
            .where(BookingSeat.booking_id == booking.id)
        )
    ).all()
    session.add(
        Outbox(
            template="booking_cancelled",
            to_email=user.email,
            payload={
                "reference": booking.reference,
                "name": user.name,
                "event_title": event.title,
                "venue_name": venue.name,
                "screen_name": screen.name,
                "starts_at": show.starts_at.isoformat(),
                "seats": [
                    f"{seat.row_label}{seat.seat_number}"
                    for _bs, seat, _cat in booked_seats
                ],
                "refund_amount": str(booking.total_amount),
            },
        )
    )

    return await _describe(session, booking, described)


async def _describe(
    session: AsyncSession, booking: Booking, offers: list[CancelledOffer]
) -> CancelResponse:
    await session.refresh(booking)
    return CancelResponse(
        reference=booking.reference,
        status=booking.status.value,
        cancelled_at=booking.cancelled_at,
        refund_amount=booking.total_amount,
        offers_created=offers,
    )
