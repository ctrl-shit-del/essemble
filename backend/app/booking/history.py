"""Booking history."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking.service import _load_show_context
from app.core.errors import forbidden, not_found
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    Seat,
    SeatCategory,
    UserAccount,
)
from app.schemas.booking import BookingShowSummary, HeldSeat
from app.schemas.waitlist import BookingListItem


async def _describe(session: AsyncSession, booking: Booking) -> BookingListItem:
    show, event, screen, venue = await _load_show_context(session, booking.show_id)
    rows = (
        await session.execute(
            select(BookingSeat, Seat, SeatCategory)
            .join(Seat, Seat.id == BookingSeat.seat_id)
            .join(SeatCategory, SeatCategory.id == BookingSeat.category_id)
            .where(BookingSeat.booking_id == booking.id)
            .order_by(Seat.y, Seat.x)
        )
    ).all()
    return BookingListItem(
        reference=booking.reference,
        status=booking.status,
        show=BookingShowSummary(
            show_id=show.id,
            event_title=event.title,
            venue_name=venue.name,
            screen_name=screen.name,
            starts_at=show.starts_at,
            language=show.language,
            format=show.format,
        ),
        seats=[
            HeldSeat(
                seat_id=seat.id,
                row_label=seat.row_label,
                seat_number=seat.seat_number,
                category_id=category.id,
                category_name=category.name,
                # The price paid, not today's price.
                price=booking_seat.price,
            )
            for booking_seat, seat, category in rows
        ],
        total=booking.total_amount,
        qr_signature=booking.qr_signature,
        checked_in_at=booking.checked_in_at,
        cancelled_at=booking.cancelled_at,
        created_at=booking.created_at,
    )


async def list_bookings(
    session: AsyncSession, user: UserAccount, status: BookingStatus | None = None
) -> list[BookingListItem]:
    query = (
        select(Booking)
        .where(Booking.user_id == user.id)
        .order_by(Booking.created_at.desc())
    )
    if status is not None:
        query = query.where(Booking.status == status)
    bookings = (await session.scalars(query)).all()
    return [await _describe(session, b) for b in bookings]


async def get_booking(
    session: AsyncSession, user: UserAccount, reference: str
) -> BookingListItem:
    booking = await session.scalar(
        select(Booking).where(Booking.reference == reference)
    )
    if booking is None:
        raise not_found("No such booking.")
    if booking.user_id != user.id:
        raise forbidden("That booking is not yours.")
    return await _describe(session, booking)
