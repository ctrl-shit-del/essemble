"""Cancellation, waitlist, offer and history routes."""

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking import cancellation, history, offers, waitlist
from app.booking.service import _load_show_context
from app.core.db import get_session
from app.identity.deps import get_current_user, require_customer
from app.models import (
    BookingStatus,
    SeatCategory,
    UserAccount,
    WaitlistEntry,
    WaitlistEntryState,
    WaitlistOffer,
    WaitlistOfferState,
)
from app.schemas.booking import BookingShowSummary, ConfirmResponse
from app.schemas.waitlist import (
    BookingListItem,
    CancelResponse,
    OfferPreview,
    WaitlistEntryResponse,
    WaitlistJoin,
    WaitlistLeaveResponse,
)

router = APIRouter(prefix="/api", tags=["waitlist"])
bookings_router = APIRouter(prefix="/api/bookings", tags=["booking"])


async def _describe_entry(
    session: AsyncSession, entry: WaitlistEntry
) -> WaitlistEntryResponse:
    show, event, screen, venue = await _load_show_context(session, entry.show_id)
    category = await session.scalar(
        select(SeatCategory).where(SeatCategory.id == entry.category_id)
    )

    offer_expires_at = None
    offer_seconds = None
    if entry.state is WaitlistEntryState.OFFERED:
        offer = await session.scalar(
            select(WaitlistOffer)
            .where(
                WaitlistOffer.entry_id == entry.id,
                WaitlistOffer.state == WaitlistOfferState.PENDING,
            )
            .order_by(WaitlistOffer.created_at.desc())
        )
        if offer is not None:
            offer_expires_at = offer.expires_at
            offer_seconds = await waitlist.offer_seconds_remaining(session, offer.id)

    return WaitlistEntryResponse(
        id=entry.id,
        show=BookingShowSummary(
            show_id=show.id,
            event_title=event.title,
            venue_name=venue.name,
            screen_name=screen.name,
            starts_at=show.starts_at,
            language=show.language,
            format=show.format,
        ),
        category_id=entry.category_id,
        category_name=category.name if category else "",
        qty=entry.qty,
        state=entry.state,
        position=(
            await waitlist.position_of(session, entry)
            if entry.state is WaitlistEntryState.WAITING
            else None
        ),
        created_at=entry.created_at,
        offer_expires_at=offer_expires_at,
        offer_seconds_remaining=offer_seconds,
    )


# ----------------------------------------------------------------- cancel


@bookings_router.post(
    "/{reference}/cancel",
    response_model=CancelResponse,
    summary="Cancel a booking",
)
async def cancel(
    reference: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CancelResponse:
    """Release the seats and hand them to the waitlist, atomically.

    Seats offered to a waitlist entry are re-claimed in this same transaction,
    so they read as `held` on the seat map from the moment the cancellation
    commits -- never as available.

    Errors:
      * `CONFLICT` (409) -- past the cancellation cutoff.
      * `FORBIDDEN` (403) -- the booking is not yours.
      * `NOT_FOUND` (404) -- no such booking.
    """
    result = await cancellation.cancel_booking(session, user, reference)
    await session.commit()
    return result


# --------------------------------------------------------------- waitlist


@router.post(
    "/waitlist",
    response_model=WaitlistEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Join the waitlist for a sold-out category",
)
async def join_waitlist(
    payload: WaitlistJoin,
    user: UserAccount = Depends(require_customer),
    session: AsyncSession = Depends(get_session),
) -> WaitlistEntryResponse:
    """Errors:
      * `NOT_SOLD_OUT` (409) -- that category still has seats.
      * `CONFLICT` (409) -- you already have a live entry for it.
      * `HOLD_LIMIT_EXCEEDED` (422) -- qty out of range.
    """
    entry = await waitlist.join(
        session, user, payload.show_id, payload.category_id, payload.qty
    )
    described = await _describe_entry(session, entry)
    await session.commit()
    return described


@router.get(
    "/waitlist",
    response_model=list[WaitlistEntryResponse],
    summary="Your waitlist entries",
)
async def my_waitlist(
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WaitlistEntryResponse]:
    """Position is computed at read time, never stored."""
    entries = (
        await session.scalars(
            select(WaitlistEntry)
            .where(WaitlistEntry.user_id == user.id)
            .order_by(WaitlistEntry.created_at.desc())
        )
    ).all()
    return [await _describe_entry(session, e) for e in entries]


@router.delete(
    "/waitlist/{entry_id}",
    response_model=WaitlistLeaveResponse,
    summary="Leave the waitlist",
)
async def leave_waitlist(
    entry_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Errors:
      * `CONFLICT` (409) -- you have a live offer; claim it or let it lapse.
      * `FORBIDDEN` (403) -- the entry is not yours.
    """
    entry = await waitlist.cancel_entry(session, user, entry_id)
    await session.commit()
    return {"id": entry.id, "state": entry.state.value}


# ------------------------------------------------------------------ offers


@router.get(
    "/waitlist/offers/{token}",
    response_model=OfferPreview,
    summary="Read an offer (no auth: the token is the credential)",
)
async def read_offer(
    token: str, session: AsyncSession = Depends(get_session)
) -> OfferPreview:
    """Errors:
      * `OFFER_EXPIRED` (410) -- lapsed, already claimed, or unknown token.
        All three answer identically on purpose.
    """
    return await offers.preview(session, token)


@router.post(
    "/waitlist/offers/{token}/claim",
    response_model=ConfirmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Claim an offer",
)
async def claim_offer(
    token: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConfirmResponse:
    """Errors:
      * `OFFER_EXPIRED` (410) -- lapsed or already claimed, indistinguishably.
      * `FORBIDDEN` (403) -- the offer was made to someone else.
    """
    result = await offers.claim(session, token, user)
    await session.commit()
    return result


# ----------------------------------------------------------------- history


@bookings_router.get("", response_model=list[BookingListItem], summary="Your bookings")
async def list_bookings(
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[BookingListItem]:
    """Newest first. Seat prices are the ones paid, not today's."""
    return await history.list_bookings(session, user, status_filter)


@bookings_router.get(
    "/{reference}", response_model=BookingListItem, summary="One booking"
)
async def get_booking(
    reference: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BookingListItem:
    """Errors:
      * `FORBIDDEN` (403) -- the booking is not yours.
      * `NOT_FOUND` (404) -- no such booking.
    """
    return await history.get_booking(session, user, reference)
