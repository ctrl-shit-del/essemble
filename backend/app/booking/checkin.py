"""Door check-in.

Same idempotency shape as confirm and offer-claim: the rowcount of a single
guarded UPDATE decides, with no pre-read of checked_in_at. A pre-check would
let two scanners at the same door both see NULL and both admit the holder.
"""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking.service import _load_show_context
from app.core.errors import AppError, ErrorCode, forbidden
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    Seat,
    UserAccount,
)
from app.notifications import qr

CHECK_IN = text(
    """
    UPDATE booking SET checked_in_at = now()
    WHERE reference = :reference AND checked_in_at IS NULL
    RETURNING checked_in_at
    """
)


class CheckinRequest(BaseModel):
    qr_payload: str


class CheckinResponse(BaseModel):
    result: str
    reference: str
    event_title: str
    venue_name: str
    screen_name: str
    starts_at: datetime
    customer_name: str
    seats: list[str]
    checked_in_at: datetime


def invalid_signature() -> AppError:
    return AppError(
        ErrorCode.INVALID_SIGNATURE,
        "That QR code is not valid.",
        400,
    )


async def verify(
    session: AsyncSession, admin: UserAccount, payload: str
) -> CheckinResponse:
    # 1. The signature, constant-time. A raw reference is not enough (I8).
    reference = qr.verify_payload(payload)
    if reference is None:
        raise invalid_signature()

    booking = await session.scalar(
        select(Booking).where(Booking.reference == reference)
    )
    if booking is None or booking.status is not BookingStatus.CONFIRMED:
        raise forbidden("That booking cannot be checked in.")

    # 2. Ownership, not just role: an admin may only admit people to shows at
    #    their own venue. Walks booking -> show -> screen -> venue -> admin_id.
    owner_id = await session.scalar(
        text(
            """
            SELECT v.admin_id
              FROM booking b
              JOIN show s   ON s.id = b.show_id
              JOIN screen c ON c.id = s.screen_id
              JOIN venue v  ON v.id = c.venue_id
             WHERE b.id = :booking_id
            """
        ),
        {"booking_id": booking.id},
    )
    if owner_id != admin.id:
        raise forbidden("That booking is not for one of your venues.")

    # Captured before the guard runs, so the ALREADY_USED response can report
    # the original timestamp after the transaction is rolled back.
    previously_checked_in = booking.checked_in_at

    # 3. The guard. rowcount 1 means we admitted them; 0 means someone already
    #    did. No pre-read of checked_in_at: two scanners at the same door would
    #    both see NULL and both admit the holder.
    checked_in_at = (
        await session.execute(CHECK_IN, {"reference": reference})
    ).scalar_one_or_none()

    show, event, screen, venue = await _load_show_context(session, booking.show_id)
    customer_name = await session.scalar(
        select(UserAccount.name).where(UserAccount.id == booking.user_id)
    )
    seats = (
        await session.execute(
            select(Seat)
            .join(BookingSeat, BookingSeat.seat_id == Seat.id)
            .where(BookingSeat.booking_id == booking.id)
            .order_by(Seat.y, Seat.x)
        )
    ).scalars().all()
    labels = [f"{s.row_label}{s.seat_number}" for s in seats]

    if checked_in_at is None:
        await session.rollback()
        raise AppError(
            ErrorCode.ALREADY_USED,
            "These tickets have already been used.",
            409,
            {
                "reference": reference,
                "checked_in_at": (
                    previously_checked_in.isoformat()
                    if previously_checked_in
                    else None
                ),
                "seats": labels,
            },
        )

    await session.commit()
    return CheckinResponse(
        result="VALID",
        reference=reference,
        event_title=event.title,
        venue_name=venue.name,
        screen_name=screen.name,
        starts_at=show.starts_at,
        customer_name=customer_name or "",
        seats=labels,
        checked_in_at=checked_in_at,
    )
