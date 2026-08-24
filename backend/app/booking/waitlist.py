"""Waitlist entries, offers, and the assignment that follows a cancellation.

Entry lifecycle and offer lookup. The assignment cascade that turns freed
seats into offers lives in `assignment.py`, shared by cancellation and the
sweeper.
"""

import hashlib
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking.sql import AVAILABLE_IN_CATEGORY, QUEUE_POSITION
from app.core.config import settings
from app.core.errors import AppError, ErrorCode, conflict, forbidden, not_found
from app.models import (
    SeatCategory,
    Show,
    UserAccount,
    WaitlistEntry,
    WaitlistEntryState,
    WaitlistOffer,
)


def hash_token(raw: str) -> str:
    """Only the hash is ever stored; the raw token lives in the email alone."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def offer_expired() -> AppError:
    """One error for expired and for already-claimed.

    Answering them differently would leak whether a token was ever valid, and
    would split single-use enforcement across two code paths instead of
    leaving it entirely in the UPDATE rowcount.
    """
    return AppError(
        ErrorCode.OFFER_EXPIRED,
        "This offer is no longer available.",
        410,
    )


async def available_in_category(
    session: AsyncSession, show_id: int, screen_id: int, category_id: int
) -> int:
    """Live availability, derived the same way the seat map derives status."""
    return await session.scalar(
        AVAILABLE_IN_CATEGORY,
        {"show_id": show_id, "screen_id": screen_id, "category_id": category_id},
    )


# --------------------------------------------------------------- entry admin


async def _load_show_and_category(
    session: AsyncSession, show_id: int, category_id: int
) -> tuple[Show, SeatCategory]:
    show = await session.scalar(select(Show).where(Show.id == show_id))
    if show is None:
        raise not_found("No such show.")
    category = await session.scalar(
        select(SeatCategory).where(
            SeatCategory.id == category_id, SeatCategory.screen_id == show.screen_id
        )
    )
    if category is None:
        raise not_found("No such seat category on this show's screen.")
    return show, category


async def join(
    session: AsyncSession, user: UserAccount, show_id: int, category_id: int, qty: int
) -> WaitlistEntry:
    """Join the queue for a sold-out category. Caller commits."""
    if not 1 <= qty <= settings.max_seats_per_hold:
        raise AppError(
            ErrorCode.HOLD_LIMIT_EXCEEDED,
            f"qty must be between 1 and {settings.max_seats_per_hold}.",
            422,
        )

    show, category = await _load_show_and_category(session, show_id, category_id)

    free = await available_in_category(session, show.id, show.screen_id, category.id)
    if free > 0:
        raise AppError(
            ErrorCode.NOT_SOLD_OUT,
            f"{category.name} still has seats; book them instead of waiting.",
            409,
            {"available": free},
        )

    entry = WaitlistEntry(
        show_id=show.id,
        category_id=category.id,
        user_id=user.id,
        qty=qty,
        state=WaitlistEntryState.WAITING,
    )
    session.add(entry)
    # The partial unique index enforces one live entry per user per show per
    # category. Flush here so the violation surfaces as a 409 from this call
    # rather than as a 500 out of the commit.
    try:
        await session.flush()
    except Exception as exc:  # IntegrityError, surfaced by the driver
        await session.rollback()
        if "uq_waitlist_entry_active_per_user" in str(exc):
            raise conflict("You are already on the waitlist for this category.")
        raise
    await session.refresh(entry)
    return entry


async def position_of(session: AsyncSession, entry: WaitlistEntry) -> int:
    """Computed on read, never stored."""
    return await session.scalar(
        QUEUE_POSITION,
        {
            "show_id": entry.show_id,
            "category_id": entry.category_id,
            "created_at": entry.created_at,
        },
    )


async def cancel_entry(
    session: AsyncSession, user: UserAccount, entry_id: int
) -> WaitlistEntry:
    entry = await session.scalar(
        select(WaitlistEntry).where(WaitlistEntry.id == entry_id)
    )
    if entry is None:
        raise not_found("No such waitlist entry.")
    if entry.user_id != user.id:
        raise forbidden("That waitlist entry is not yours.")
    if entry.state is WaitlistEntryState.OFFERED:
        # Dropping it here would strand the seats the offer is holding until
        # the sweeper notices. Let it lapse or claim it.
        raise conflict(
            "You have a live offer for this category. Claim it or let it lapse."
        )
    if entry.state is not WaitlistEntryState.WAITING:
        raise conflict(f"That entry is already {entry.state.value}.")

    entry.state = WaitlistEntryState.CANCELLED
    return entry


# ---------------------------------------------------------------- the offer


async def load_offer_by_token(
    session: AsyncSession, token: str
) -> tuple[WaitlistOffer, WaitlistEntry]:
    offer = await session.scalar(
        select(WaitlistOffer).where(WaitlistOffer.token_hash == hash_token(token))
    )
    if offer is None:
        # Same answer as a lapsed offer: an unknown token must not be
        # distinguishable from a spent one.
        raise offer_expired()
    entry = await session.scalar(
        select(WaitlistEntry).where(WaitlistEntry.id == offer.entry_id)
    )
    if entry is None:
        raise offer_expired()
    return offer, entry


async def offer_is_live(session: AsyncSession, offer: WaitlistOffer) -> bool:
    return bool(
        await session.scalar(
            text(
                "SELECT state = 'pending' AND expires_at > now()"
                " FROM waitlist_offer WHERE id = :id"
            ),
            {"id": offer.id},
        )
    )


async def offer_seconds_remaining(session: AsyncSession, offer_id: int) -> int:
    return await session.scalar(
        text(
            "SELECT greatest(0, extract(epoch FROM (expires_at - now())))::int"
            " FROM waitlist_offer WHERE id = :id"
        ),
        {"id": offer_id},
    )


async def hold_group_for_offer(session: AsyncSession, offer_id: int) -> UUID:
    """The group the offer's re-claimed seats were written under."""
    return await session.scalar(
        text(
            "SELECT hold_group_id FROM seat_claim"
            " WHERE holder_type = 'waitlist_offer' AND holder_id = :id LIMIT 1"
        ),
        {"id": offer_id},
    )
