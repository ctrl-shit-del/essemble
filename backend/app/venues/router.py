"""Admin venue routes.

Every route here is gated twice: `require_admin` proves the caller is an admin,
and the service re-derives ownership of the named resource from the database.
The role check alone would let any admin edit any venue.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.identity.deps import require_admin
from app.models import UserAccount
from app.schemas.venue import (
    LayoutRequest,
    LayoutResponse,
    ScreenCreate,
    ScreenResponse,
    VenueCreate,
    VenueResponse,
)
from app.venues import service

router = APIRouter(prefix="/api/admin", tags=["venues", "admin"])


@router.get("/venues", response_model=list[VenueResponse], summary="Your venues")
async def list_venues(
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[VenueResponse]:
    """Scoped to the calling admin. Never lists another admin's venues."""
    return await service.list_venues(session, admin)


@router.post(
    "/venues",
    response_model=VenueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a venue",
)
async def create_venue(
    payload: VenueCreate,
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """`booking_policy='request'` makes organisers file a request instead of
    scheduling directly.

    Errors:
      * `FORBIDDEN` (403) -- caller is not an admin.
    """
    return await service.create_venue(session, admin, payload)


@router.post(
    "/venues/{venue_id}/screens",
    response_model=ScreenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a screen to a venue",
)
async def create_screen(
    venue_id: int,
    payload: ScreenCreate,
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ScreenResponse:
    """Errors:
      * `FORBIDDEN` (403) -- the venue is not yours, or does not exist.
      * `CONFLICT` (409) -- the venue already has a screen by that name.
    """
    return await service.create_screen(session, admin, venue_id, payload)


@router.post(
    "/screens/{screen_id}/layout",
    response_model=LayoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate the seat layout for a screen",
)
async def generate_layout(
    screen_id: int,
    payload: LayoutRequest,
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> LayoutResponse:
    """Generate categories and every seat, with aisle-aware x coordinates.

    Errors:
      * `FORBIDDEN` (403) -- the screen is not yours, or does not exist.
      * `CONFLICT` (409) -- a seat_claim exists for some show on this screen;
        regenerating would orphan booking_seat rows.
      * `VALIDATION_ERROR` (422) -- rows not covered by exactly one category.
    """
    return await service.generate_layout(session, admin, screen_id, payload)
