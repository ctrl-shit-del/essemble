"""Seat map, hold acquisition and confirmation.

The two rules that shape this whole module:

  I4 -- seat acquisition is one INSERT ... ON CONFLICT per seat. There is no
        availability read anywhere in the hold path. Availability is resolved
        by the INSERT itself; any SELECT beforehand reintroduces the race the
        design removes.

  I3 -- expiry is authoritative via expires_at, not via the sweeper. Every read
        filters `expires_at > now()`, and acquisition takes over an
        already-expired claim in the same statement.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking.events import bump_and_notify
from app.booking.sql import (
    ACQUIRE_SEAT,
    CONFIRM_HOLD,
    HOLD_REMAINING,
    RELEASE_HOLD,
    SEAT_MAP,
)
from app.core.config import settings
from app.core.errors import AppError, ErrorCode, forbidden, not_found, validation_error
from app.core.security import new_reference, qr_signature
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    Event,
    Outbox,
    Screen,
    Seat,
    SeatCategory,
    Show,
    ShowCategoryPrice,
    ShowStatus,
    UserAccount,
    Venue,
)
from app.schemas.booking import (
    BookingShowSummary,
    ConfirmResponse,
    HeldSeat,
    HoldCreate,
    HoldResponse,
    SeatMapCategory,
    SeatMapResponse,
    SeatMapSeat,
)

REFERENCE_ATTEMPTS = 5


class NotModified(Exception):
    """Raised to signal a 304; carries no body by definition."""


def seat_unavailable(seat_ids: list[int]) -> AppError:
    return AppError(
        ErrorCode.SEAT_UNAVAILABLE,
        "One or more seats are no longer available.",
        409,
        {"seat_ids": sorted(seat_ids)},
    )


def hold_expired() -> AppError:
    return AppError(
        ErrorCode.HOLD_EXPIRED,
        "That hold has expired. The seats were released.",
        410,
    )


# ------------------------------------------------------------------ seat map


async def _load_show_context(
    session: AsyncSession, show_id: int
) -> tuple[Show, Event, Screen, Venue]:
    row = (
        await session.execute(
            select(Show, Event, Screen, Venue)
            .join(Event, Event.id == Show.event_id)
            .join(Screen, Screen.id == Show.screen_id)
            .join(Venue, Venue.id == Screen.venue_id)
            .where(Show.id == show_id)
        )
    ).first()
    if row is None:
        raise not_found("No such show.")
    return row[0], row[1], row[2], row[3]


async def get_seat_map(
    session: AsyncSession, show_id: int, since: int | None = None
) -> SeatMapResponse:
    show, event, screen, venue = await _load_show_context(session, show_id)

    if since is not None and since == show.seat_version:
        raise NotModified

    categories = (
        await session.execute(
            select(SeatCategory, ShowCategoryPrice.price)
            .join(
                ShowCategoryPrice,
                (ShowCategoryPrice.category_id == SeatCategory.id)
                & (ShowCategoryPrice.show_id == show.id),
            )
            .where(SeatCategory.screen_id == screen.id)
            .order_by(SeatCategory.rank)
        )
    ).all()

    rows = (
        await session.execute(
            SEAT_MAP, {"show_id": show.id, "screen_id": screen.id}
        )
    ).mappings()

    seats = [
        SeatMapSeat(
            seat_id=row["id"],
            row_label=row["row_label"],
            seat_number=row["seat_number"],
            x=row["x"],
            y=row["y"],
            category_id=row["category_id"],
            status=row["status"],
        )
        for row in rows
    ]

    return SeatMapResponse(
        show_id=show.id,
        seat_version=show.seat_version,
        event_title=event.title,
        venue_name=venue.name,
        screen_name=screen.name,
        starts_at=show.starts_at,
        language=show.language,
        format=show.format,
        rows=(max((s.y for s in seats), default=-1) + 1),
        columns=max((s.x for s in seats), default=0),
        categories=[
            SeatMapCategory(
                id=category.id, name=category.name, rank=category.rank, price=price
            )
            for category, price in categories
        ],
        seats=seats,
    )


# ---------------------------------------------------------------- validation


async def _validate_hold_request(
    session: AsyncSession, user: UserAccount, payload: HoldCreate
) -> Show:
    """Static checks only.

    Deliberately says nothing about whether the requested seats are free --
    that question is answered by the INSERT, and asking it here would be the
    check-then-act race this design exists to remove.
    """
    show = await session.scalar(select(Show).where(Show.id == payload.show_id))
    if show is None:
        raise not_found("No such show.")
    if show.status is not ShowStatus.SCHEDULED:
        raise validation_error(f"That show is {show.status.value}.")

    in_future = await session.scalar(
        text("SELECT starts_at > now() FROM show WHERE id = :id"), {"id": show.id}
    )
    if not in_future:
        raise validation_error("That show has already started.")

    seat_ids = payload.seat_ids
    if len(set(seat_ids)) != len(seat_ids):
        raise validation_error(
            "seat_ids contains duplicates.", {"seat_ids": sorted(seat_ids)}
        )
    if len(seat_ids) > settings.max_seats_per_hold:
        raise AppError(
            ErrorCode.HOLD_LIMIT_EXCEEDED,
            f"A single hold may cover at most {settings.max_seats_per_hold} seats.",
            422,
            {"requested": len(seat_ids), "limit": settings.max_seats_per_hold},
        )

    valid = set(
        (
            await session.scalars(
                select(Seat.id).where(
                    Seat.id.in_(seat_ids),
                    Seat.screen_id == show.screen_id,
                    Seat.is_active.is_(True),
                )
            )
        ).all()
    )
    stray = sorted(set(seat_ids) - valid)
    if stray:
        raise validation_error(
            "Some seats do not belong to this show's screen, or are inactive.",
            {"seat_ids": stray},
        )

    # One live hold group per user per show. This reads seat_claim, but it asks
    # about the caller's own holds, not about the availability of the seats
    # being requested.
    existing = await session.scalar(
        text(
            """
            SELECT hold_group_id FROM seat_claim
             WHERE show_id = :show_id AND holder_type = 'user'
               AND holder_id = :user_id
               AND state = 'held' AND expires_at > now()
             LIMIT 1
            """
        ),
        {"show_id": show.id, "user_id": user.id},
    )
    if existing is not None:
        raise AppError(
            ErrorCode.HOLD_LIMIT_EXCEEDED,
            "You already hold seats for this show. Release them first.",
            409,
            {"hold_group_id": str(existing)},
        )

    return show


# ------------------------------------------------------------------- pricing


async def _priced_seats(
    session: AsyncSession, show_id: int, seat_ids: list[int]
) -> list[HeldSeat]:
    """Seat rows with the price frozen from this show's category pricing."""
    rows = (
        await session.execute(
            select(Seat, SeatCategory, ShowCategoryPrice.price)
            .join(SeatCategory, SeatCategory.id == Seat.category_id)
            .join(
                ShowCategoryPrice,
                (ShowCategoryPrice.category_id == SeatCategory.id)
                & (ShowCategoryPrice.show_id == show_id),
            )
            .where(Seat.id.in_(seat_ids))
            .order_by(Seat.y, Seat.x)
        )
    ).all()
    if len(rows) != len(seat_ids):
        raise validation_error(
            "This show has no price for one of the requested seat categories."
        )
    return [
        HeldSeat(
            seat_id=seat.id,
            row_label=seat.row_label,
            seat_number=seat.seat_number,
            category_id=category.id,
            category_name=category.name,
            price=price,
        )
        for seat, category, price in rows
    ]


# ------------------------------------------------------------------- acquire


async def create_hold(
    session: AsyncSession, user: UserAccount, payload: HoldCreate
) -> HoldResponse:
    show = await _validate_hold_request(session, user, payload)

    group = uuid4()
    ttl = settings.hold_ttl_seconds
    lost: list[int] = []

    # Ascending seat_id order is deadlock avoidance: two callers racing for
    # {5, 9} and {9, 5} must not take the rows in opposite orders.
    for seat_id in sorted(payload.seat_ids):
        won = (
            await session.execute(
                ACQUIRE_SEAT,
                {
                    "show_id": show.id,
                    "seat_id": seat_id,
                    "group": str(group),
                    "user_id": user.id,
                    "ttl": ttl,
                },
            )
        ).scalar_one_or_none()
        if won is None:
            # Keep going so the client is told about every unavailable seat
            # rather than only the first. The transaction is doomed either way.
            lost.append(seat_id)

    if lost:
        # All-or-nothing (I5). No partial success, and no retry: a retry would
        # be a second chance at a seat someone else has legitimately taken.
        await session.rollback()
        raise seat_unavailable(lost)

    await bump_and_notify(session, show.id, (payload.seat_ids, "held"))

    seats = await _priced_seats(session, show.id, payload.seat_ids)
    summary = (
        await session.execute(HOLD_REMAINING, {"group": str(group)})
    ).mappings().one()

    return HoldResponse(
        hold_group_id=group,
        show_id=show.id,
        expires_at=summary["expires_at"],
        seconds_remaining=summary["seconds_remaining"],
        seats=seats,
        total=sum((s.price for s in seats), Decimal("0.00")),
    )


# ------------------------------------------------------------- read / release


async def _load_group(
    session: AsyncSession, group_id: UUID, user: UserAccount
) -> dict:
    """Group metadata: owner, show, seat count, remaining time.

    Reads state only to report it. Nothing in the confirm path branches on
    what this returns before the guarding UPDATE has run.
    """
    row = (
        await session.execute(HOLD_REMAINING, {"group": str(group_id)})
    ).mappings().first()
    if row is None:
        raise not_found("No such hold.")
    if row["holder_id"] != user.id:
        raise forbidden("That hold is not yours.")
    return dict(row)


async def get_hold(
    session: AsyncSession, group_id: UUID, user: UserAccount
) -> HoldResponse:
    row = await _load_group(session, group_id, user)
    if not row["still_held"]:
        raise hold_expired()

    seat_ids = (
        await session.scalars(
            text("SELECT seat_id FROM seat_claim WHERE hold_group_id = :g"),
            {"g": str(group_id)},
        )
    ).all()
    seats = await _priced_seats(session, row["show_id"], list(seat_ids))
    return HoldResponse(
        hold_group_id=group_id,
        show_id=row["show_id"],
        expires_at=row["expires_at"],
        seconds_remaining=row["seconds_remaining"],
        seats=seats,
        total=sum((s.price for s in seats), Decimal("0.00")),
    )


async def release_hold(
    session: AsyncSession, group_id: UUID, user: UserAccount
) -> dict:
    """Release early. Idempotent: releasing twice is not an error."""
    row = await _load_group(session, group_id, user)
    released = (
        (await session.execute(RELEASE_HOLD, {"group": str(group_id)})).scalars().all()
    )
    if released:
        await bump_and_notify(
            session, row["show_id"], (list(released), "available")
        )
    return {
        "hold_group_id": str(group_id),
        "released_seat_ids": sorted(released),
        "already_released": not released,
    }


# ------------------------------------------------------------------- confirm


async def _unique_reference(session: AsyncSession) -> str:
    """A reference that is not already taken.

    Collision is vanishingly unlikely at 36^6, but the unique index is the
    authority, so the loop is bounded rather than optimistic.
    """
    for _ in range(REFERENCE_ATTEMPTS):
        candidate = new_reference()
        clash = await session.scalar(
            select(Booking.id).where(Booking.reference == candidate)
        )
        if clash is None:
            return candidate
    raise AppError(
        ErrorCode.CONFLICT, "Could not allocate a booking reference.", 503
    )


async def confirm_hold(
    session: AsyncSession, group_id: UUID, user: UserAccount
) -> ConfirmResponse:
    row = await _load_group(session, group_id, user)
    expected = row["seat_count"]

    # The rowcount of this UPDATE is the entire guard. Nothing above it read
    # the hold's validity: a pre-check would open a TOCTOU window between the
    # check and the write.
    booked = (
        (await session.execute(CONFIRM_HOLD, {"group": str(group_id)})).scalars().all()
    )
    if len(booked) != expected:
        await session.rollback()
        raise hold_expired()

    return await create_booking(session, user, row["show_id"], group_id, list(booked))


async def create_booking(
    session: AsyncSession,
    user: UserAccount,
    show_id: int,
    hold_group_id: UUID,
    seat_ids: list[int],
) -> ConfirmResponse:
    """Turn already-booked claims into a booking, with its QR and its email.

    Extracted so the waitlist-offer claim path in 3.6 runs the identical code
    rather than a second copy of it: both arrive here with the seats already
    flipped to 'booked' by their own guard. Caller commits.
    """
    show, event, screen, venue = await _load_show_context(session, show_id)
    seats = await _priced_seats(session, show.id, seat_ids)
    total = sum((s.price for s in seats), Decimal("0.00"))

    reference = await _unique_reference(session)
    booking = Booking(
        reference=reference,
        show_id=show.id,
        user_id=user.id,
        hold_group_id=hold_group_id,
        total_amount=total,
        status=BookingStatus.CONFIRMED,
        qr_signature=qr_signature(reference),
    )
    session.add(booking)
    await session.flush()
    await session.refresh(booking)

    session.add_all(
        BookingSeat(
            booking_id=booking.id,
            seat_id=seat.seat_id,
            category_id=seat.category_id,
            # Frozen here. Re-pricing the show later must never rewrite it.
            price=seat.price,
        )
        for seat in seats
    )

    # Never send mail inline (I7). The transaction records the intent; the
    # Phase 4 dispatcher delivers it, and a provider outage cannot roll back a
    # confirmed booking.
    session.add(
        Outbox(
            template="booking_confirmation",
            to_email=user.email,
            payload={
                "reference": reference,
                "name": user.name,
                "event_title": event.title,
                "venue_name": venue.name,
                "screen_name": screen.name,
                "starts_at": show.starts_at.isoformat(),
                "language": show.language,
                "format": show.format.value if show.format else None,
                "seats": [
                    {
                        "label": f"{seat.row_label}{seat.seat_number}",
                        "category": seat.category_name,
                        "price": str(seat.price),
                    }
                    for seat in seats
                ],
                "total": str(total),
                "qr_signature": booking.qr_signature,
            },
        )
    )

    await bump_and_notify(session, show.id, (seat_ids, "booked"))

    return ConfirmResponse(
        reference=reference,
        status=BookingStatus.CONFIRMED.value,
        show=BookingShowSummary(
            show_id=show.id,
            event_title=event.title,
            venue_name=venue.name,
            screen_name=screen.name,
            starts_at=show.starts_at,
            language=show.language,
            format=show.format,
        ),
        seats=seats,
        total=total,
        qr_signature=booking.qr_signature or "",
        created_at=booking.created_at,
    )
