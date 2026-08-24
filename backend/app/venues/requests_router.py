"""Venue-request routes, organiser side and admin side."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.identity.deps import require_admin, require_organiser
from app.models import UserAccount, VenueRequestState
from app.schemas.venue_request import (
    DecisionRequest,
    DecisionResponse,
    VenueRequestResponse,
)
from app.venues import requests_service

organiser_router = APIRouter(
    prefix="/api/organiser", tags=["venues", "organiser"]
)
admin_router = APIRouter(prefix="/api/admin", tags=["venues", "admin"])


@organiser_router.get(
    "/venue-requests",
    response_model=list[VenueRequestResponse],
    summary="Your venue requests",
)
async def list_my_requests(
    organiser: UserAccount = Depends(require_organiser),
    session: AsyncSession = Depends(get_session),
) -> list[VenueRequestResponse]:
    """Scoped to the calling organiser."""
    return await requests_service.list_for_organiser(session, organiser)


@admin_router.get(
    "/venue-requests",
    response_model=list[VenueRequestResponse],
    summary="Requests against your venues",
)
async def list_venue_requests(
    state: VenueRequestState | None = Query(default=None),
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[VenueRequestResponse]:
    """Requests for venues this admin owns -- never the global pending queue.

    The scoping is a join on venue.admin_id, not a filter applied to a full
    listing.
    """
    return await requests_service.list_for_admin(session, admin, state)


@admin_router.post(
    "/venue-requests/{request_id}/decision",
    response_model=DecisionResponse,
    summary="Approve or reject a venue request",
)
async def decide(
    request_id: int,
    payload: DecisionRequest,
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    """Approval creates the show and its prices in one transaction.

    The slot is re-checked here against live data: it may have been taken
    through the normal path while this request sat pending, and two pending
    requests for the same slot can both reach this point.

    Errors:
      * `FORBIDDEN` (403) -- the request is not against one of your venues.
      * `CONFLICT` (409) -- already decided, or the slot is no longer free.
      * `VALIDATION_ERROR` (422) -- proposed_pricing no longer matches the
        screen's seat categories (the layout was regenerated).
    """
    return await requests_service.decide(session, admin, request_id, payload)
