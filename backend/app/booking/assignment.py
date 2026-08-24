"""Waitlist assignment: the one implementation of steps (d)-(g).

Two callers, one implementation:

  * cancellation.cancel_booking -- seats freed because a customer cancelled
  * workers.sweeper             -- seats freed because an offer lapsed

Neither commits here. `assign_freed_seats` runs inside the caller's
transaction and the caller owns the boundary, because on the cancellation path
the seats must never be visible as available between being released and being
re-claimed for an offer (I6).
"""

import secrets
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking.service import _load_show_context, _priced_seats
from app.booking.events import bump_and_notify
from app.booking.sql import (
    ACQUIRE_SEAT_FOR_OFFER,
    INSERT_OFFER,
    NEXT_WAITLIST_ENTRY,
)
from app.booking.waitlist import hash_token
from app.core.config import settings
from app.models import Outbox, Seat, SeatCategory, ShowCategoryPrice, UserAccount


@dataclass
class OfferOutcome:
    offer_id: int
    entry_id: int
    user_id: int
    seat_ids: list[int]
    seat_labels: list[str]
    category_id: int
    category_name: str
    expires_at: datetime


async def assign_freed_seats(
    session: AsyncSession, show_id: int, seat_ids: list[int]
) -> list[OfferOutcome]:
    """Offer freed seats to the waitlist, or leave them available.

    Steps (d) through (g) of 3.4:
      (d) pick the oldest fitting waiting entry per category
      (e) create the offer, re-claim the seats for it, stage the email
      (f) seats nobody fits stay released and become available
      (g) bump seat_version

    Returns what was offered so the caller can report or log it.
    """
    if not seat_ids:
        return []

    show, event, screen, venue = await _load_show_context(session, show_id)

    # (c) group by category
    by_category: dict[int, list[int]] = {}
    rows = (
        await session.execute(
            select(Seat.id, Seat.category_id).where(Seat.id.in_(list(seat_ids)))
        )
    ).all()
    for seat_id, category_id in rows:
        by_category.setdefault(category_id, []).append(seat_id)

    outcomes: list[OfferOutcome] = []

    for category_id, category_seats in by_category.items():
        remaining = sorted(category_seats)

        # Keep serving while seats remain in this category and entries fit.
        while remaining:
            entry_row = (
                await session.execute(
                    NEXT_WAITLIST_ENTRY,
                    {
                        "show_id": show.id,
                        "category_id": category_id,
                        "freed": len(remaining),
                    },
                )
            ).first()
            if entry_row is None:
                # (f) nobody fits; the rest stay released and available.
                break

            entry_id, entry_user_id, qty = entry_row
            seats_for_offer = remaining[:qty]
            remaining = remaining[qty:]

            outcome = await _offer_seats(
                session,
                show,
                entry_id,
                entry_user_id,
                category_id,
                seats_for_offer,
                event.title,
                venue.name,
            )
            outcomes.append(outcome)

    # (g) the seat map moved either way. Seats handed to an offer are 'held'
    # from this instant (I6); anything nobody fitted is genuinely available.
    offered = [seat for outcome in outcomes for seat in outcome.seat_ids]
    freed = [seat for seat in seat_ids if seat not in set(offered)]
    await bump_and_notify(
        session, show.id, (offered, "held"), (freed, "available")
    )
    return outcomes


async def _offer_seats(
    session: AsyncSession,
    show,
    entry_id: int,
    entry_user_id: int,
    category_id: int,
    seats_for_offer: list[int],
    event_title: str,
    venue_name: str,
) -> OfferOutcome:
    """(e): create the offer, re-claim the seats, stage the email."""
    # Only the hash is stored. The raw token exists in memory and in the email
    # payload, and is never written anywhere else.
    raw_token = secrets.token_urlsafe(32)
    offer_id, expires_at = (
        await session.execute(
            INSERT_OFFER,
            {
                "entry_id": entry_id,
                "seat_ids": seats_for_offer,
                "token_hash": hash_token(raw_token),
                "ttl": settings.waitlist_offer_ttl_seconds,
            },
        )
    ).one()

    await session.execute(
        text("UPDATE waitlist_entry SET state = 'offered' WHERE id = :id"),
        {"id": entry_id},
    )

    # I6. Same statement and same partial unique index as ordinary
    # acquisition, so the offer inherits the concurrency guarantee: from here
    # the seats are held for this offer and nobody browsing can take them.
    group = uuid4()
    for seat_id in seats_for_offer:
        won = (
            await session.execute(
                ACQUIRE_SEAT_FOR_OFFER,
                {
                    "show_id": show.id,
                    "seat_id": seat_id,
                    "group": str(group),
                    "holder_id": offer_id,
                    "expires_at": expires_at,
                },
            )
        ).scalar_one_or_none()
        if won is None:
            # Unreachable by construction: these seats were released a few
            # statements ago in this same transaction. Loud, because handing
            # out an offer for seats we do not hold is worse than failing.
            raise RuntimeError(
                f"failed to re-claim seat {seat_id} for offer {offer_id}"
            )

    seats = await _priced_seats(session, show.id, seats_for_offer)
    labels = [f"{s.row_label}{s.seat_number}" for s in seats]
    category = await session.scalar(
        select(SeatCategory).where(SeatCategory.id == category_id)
    )
    unit_price = await session.scalar(
        select(ShowCategoryPrice.price).where(
            ShowCategoryPrice.show_id == show.id,
            ShowCategoryPrice.category_id == category_id,
        )
    ) or Decimal("0.00")

    user = await session.scalar(
        select(UserAccount).where(UserAccount.id == entry_user_id)
    )
    if user is not None:
        session.add(
            Outbox(
                template="waitlist_offer",
                to_email=user.email,
                payload={
                    "name": user.name,
                    "event_title": event_title,
                    "venue_name": venue_name,
                    "starts_at": show.starts_at.isoformat(),
                    "category": category.name if category else "",
                    "seats": labels,
                    "unit_price": str(unit_price),
                    "total": str(unit_price * len(labels)),
                    "expires_at": expires_at.isoformat(),
                    "claim_url": f"{settings.app_base_url}/offers/{raw_token}",
                },
            )
        )

    return OfferOutcome(
        offer_id=offer_id,
        entry_id=entry_id,
        user_id=entry_user_id,
        seat_ids=seats_for_offer,
        seat_labels=labels,
        category_id=category_id,
        category_name=category.name if category else "",
        expires_at=expires_at,
    )
