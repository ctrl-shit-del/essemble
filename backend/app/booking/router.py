"""Seat map, holds and confirmation routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking import service
from app.core.db import get_session
from app.core.idempotency import Idempotency, get_idempotency
from app.identity.deps import get_current_user, require_customer
from app.models import UserAccount
from app.schemas.booking import (
    ConfirmResponse,
    HoldCreate,
    HoldReleaseResponse,
    HoldResponse,
    SeatMapResponse,
)

router = APIRouter(prefix="/api", tags=["booking"])

HOLDS_ENDPOINT = "POST /api/holds"
CONFIRM_ENDPOINT = "POST /api/holds/{id}/confirm"


@router.get(
    "/shows/{show_id}/seatmap",
    response_model=SeatMapResponse,
    summary="Seat map with derived status",
)
async def seat_map(
    show_id: int,
    since: int | None = Query(default=None, description="Last seen seat_version"),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Every seat's status is derived from seat_claim at read time.

    An expired-but-unswept hold reads as `available`: expiry is authoritative
    via `expires_at`, not via the sweeper having run.

    Pass `?since=<seat_version>`; if nothing has changed you get 304 with no
    body.

    Errors:
      * `NOT_FOUND` (404) -- no such show.
    """
    try:
        return await service.get_seat_map(session, show_id, since)
    except service.NotModified:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)


@router.post(
    "/holds",
    response_model=HoldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Hold seats",
)
async def create_hold(
    payload: HoldCreate,
    user: UserAccount = Depends(require_customer),
    session: AsyncSession = Depends(get_session),
    idem: Idempotency = Depends(get_idempotency),
) -> Any:
    """Acquire seats for a limited time.

    All-or-nothing: if any seat is lost the whole transaction rolls back and
    nothing is held. Seats are taken in ascending seat_id order so that two
    callers requesting the same seats in different orders cannot deadlock.

    Errors:
      * `SEAT_UNAVAILABLE` (409) -- `details.seat_ids` lists the seats lost.
      * `HOLD_LIMIT_EXCEEDED` (409/422) -- too many seats, or you already hold
        seats for this show.
      * `VALIDATION_ERROR` (422) -- seats not on this show's screen, duplicates,
        or the show is cancelled or already started.
      * `NOT_FOUND` (404) -- no such show.
    """
    replayed = await idem.replay(user.id, HOLDS_ENDPOINT)
    if replayed is not None:
        return replayed

    result = await service.create_hold(session, user, payload)
    return await idem.commit_with(
        user.id,
        HOLDS_ENDPOINT,
        result.model_dump(mode="json"),
        status.HTTP_201_CREATED,
    )


@router.get(
    "/holds/{group_id}", response_model=HoldResponse, summary="Time left on a hold"
)
async def get_hold(
    group_id: UUID,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HoldResponse:
    """Errors:
      * `NOT_FOUND` (404) -- no such hold group.
      * `FORBIDDEN` (403) -- the hold is not yours.
      * `HOLD_EXPIRED` (410) -- the hold lapsed.
    """
    return await service.get_hold(session, group_id, user)


@router.delete(
    "/holds/{group_id}",
    response_model=HoldReleaseResponse,
    summary="Release a hold early",
)
async def release_hold(
    group_id: UUID,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Idempotent: releasing an already-released hold is not an error.

    Errors:
      * `NOT_FOUND` (404) -- no such hold group.
      * `FORBIDDEN` (403) -- the hold is not yours.
    """
    result = await service.release_hold(session, group_id, user)
    await session.commit()
    return result


@router.post(
    "/holds/{group_id}/confirm",
    response_model=ConfirmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm a hold into a booking",
)
async def confirm_hold(
    group_id: UUID,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    idem: Idempotency = Depends(get_idempotency),
) -> Any:
    """Turn a live hold into a confirmed booking. Payment is mocked.

    The guard is the rowcount of a single UPDATE: if it does not cover every
    seat in the group, the hold lapsed and nothing is written.

    Errors:
      * `HOLD_EXPIRED` (410) -- the hold lapsed; no booking was created.
      * `FORBIDDEN` (403) -- the hold is not yours.
      * `NOT_FOUND` (404) -- no such hold group.
    """
    replayed = await idem.replay(user.id, CONFIRM_ENDPOINT)
    if replayed is not None:
        return replayed

    result = await service.confirm_hold(session, group_id, user)
    return await idem.commit_with(
        user.id,
        CONFIRM_ENDPOINT,
        result.model_dump(mode="json"),
        status.HTTP_201_CREATED,
    )
