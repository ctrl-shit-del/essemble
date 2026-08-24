"""Reading and claiming a time-limited waitlist offer."""

from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking import waitlist
from app.booking.service import _load_show_context, _priced_seats, create_booking
from app.booking.sql import BOOK_OFFER_SEATS, CLAIM_OFFER
from app.core.errors import forbidden
from app.models import SeatCategory, UserAccount, WaitlistEntry
from app.schemas.booking import BookingShowSummary, ConfirmResponse
from app.schemas.waitlist import OfferPreview


async def preview(session: AsyncSession, token: str) -> OfferPreview:
    """Unauthenticated: the token IS the credential."""
    offer, entry = await waitlist.load_offer_by_token(session, token)
    if not await waitlist.offer_is_live(session, offer):
        raise waitlist.offer_expired()

    show, event, screen, venue = await _load_show_context(session, entry.show_id)
    seats = await _priced_seats(session, show.id, list(offer.seat_ids))
    category = await session.scalar(
        select(SeatCategory).where(SeatCategory.id == entry.category_id)
    )

    return OfferPreview(
        show=BookingShowSummary(
            show_id=show.id,
            event_title=event.title,
            venue_name=venue.name,
            screen_name=screen.name,
            starts_at=show.starts_at,
            language=show.language,
            format=show.format,
        ),
        category_name=category.name if category else "",
        seats=seats,
        total=sum((s.price for s in seats), Decimal("0.00")),
        expires_at=offer.expires_at,
        seconds_remaining=await waitlist.offer_seconds_remaining(session, offer.id),
    )


async def claim(
    session: AsyncSession, token: str, user: UserAccount
) -> ConfirmResponse:
    """Convert an offer into a booking. Caller commits.

    There is no pre-check on the offer's state. Single-use enforcement lives
    entirely in the rowcount of CLAIM_OFFER, which is also why an expired offer
    and an already-claimed one produce the identical error.
    """
    offer, entry = await waitlist.load_offer_by_token(session, token)

    if entry.user_id != user.id:
        raise forbidden("This offer was made to someone else.")

    claimed = (
        await session.execute(CLAIM_OFFER, {"offer_id": offer.id})
    ).scalar_one_or_none()
    if claimed is None:
        raise waitlist.offer_expired()

    booked = (
        (await session.execute(BOOK_OFFER_SEATS, {"offer_id": offer.id}))
        .scalars()
        .all()
    )
    if len(booked) != len(offer.seat_ids):
        # The offer was live but its seats were not: roll the whole thing back
        # rather than issue a booking for seats we no longer hold.
        await session.rollback()
        raise waitlist.offer_expired()

    await session.execute(
        text("UPDATE waitlist_entry SET state = 'converted' WHERE id = :id"),
        {"id": entry.id},
    )

    # Identical path to 3.3, not a second copy of it.
    group = await waitlist.hold_group_for_offer(session, offer.id)
    return await create_booking(session, user, entry.show_id, group, list(booked))
