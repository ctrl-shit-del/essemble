"""Organiser catalog routes and the public browse surface."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import scheduling, service
from app.core.db import get_session
from app.identity.deps import require_organiser
from app.models import EventType, ShowFormat, UserAccount
from app.schemas.catalog import (
    EventCreate,
    EventListItem,
    EventResponse,
    Section,
    ShowCreate,
    ShowDetail,
    ShowResponse,
    ShowUpdate,
    VenueShowtimes,
)
from app.schemas.venue_request import ShowScheduleResult

organiser_router = APIRouter(
    prefix="/api/organiser", tags=["catalog", "organiser"]
)
public_router = APIRouter(prefix="/api", tags=["catalog"])


# ------------------------------------------------------------------ organiser


@organiser_router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event",
)
async def create_event(
    payload: EventCreate,
    organiser: UserAccount = Depends(require_organiser),
    session: AsyncSession = Depends(get_session),
) -> EventResponse:
    """Errors:
      * `FORBIDDEN` (403) -- caller is not an organiser.
      * `VALIDATION_ERROR` (422) -- a movie without runtime_min, or a live
        event without artist_name.
    """
    return await service.create_event(session, organiser, payload)


@organiser_router.post(
    "/shows",
    response_model=ShowScheduleResult,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a show, or request a slot",
)
async def create_show(
    payload: ShowCreate,
    response: Response,
    organiser: UserAccount = Depends(require_organiser),
    session: AsyncSession = Depends(get_session),
) -> ShowScheduleResult:
    """201 with `status='created'` at an `open` venue.

    202 with `status='pending_approval'` at a `request` venue -- a
    venue_request is written carrying the submitted pricing, and no `show` row
    is created until an admin approves.

    Errors:
      * `FORBIDDEN` (403) -- the event is not yours.
      * `NOT_FOUND` (404) -- no such screen.
      * `CONFLICT` (409) -- another show occupies the slot, runtime plus a
        30-minute buffer.
      * `VALIDATION_ERROR` (422) -- starts_at in the past, or pricing that does
        not name exactly the screen's seat categories.
    """
    result, code = await scheduling.schedule_show(session, organiser, payload)
    response.status_code = code
    return result


@organiser_router.get(
    "/shows", response_model=list[ShowResponse], summary="Your shows"
)
async def list_shows(
    organiser: UserAccount = Depends(require_organiser),
    session: AsyncSession = Depends(get_session),
) -> list[ShowResponse]:
    return await service.list_own_shows(session, organiser)


@organiser_router.patch(
    "/shows/{show_id}", response_model=ShowResponse, summary="Amend a show"
)
async def update_show(
    show_id: int,
    payload: ShowUpdate,
    organiser: UserAccount = Depends(require_organiser),
    session: AsyncSession = Depends(get_session),
) -> ShowResponse:
    """Moving starts_at re-runs the overlap check, excluding this show.

    Errors:
      * `FORBIDDEN` (403) -- the show is not yours.
      * `CONFLICT` (409) -- the new slot clashes.
      * `VALIDATION_ERROR` (422) -- past starts_at, or pricing mismatch.
    """
    return await service.update_show(session, organiser, show_id, payload)


# --------------------------------------------------------------------- public


@public_router.get("/events", response_model=list[EventListItem], summary="Browse")
async def list_events(
    type: EventType | None = Query(default=None),
    city: str | None = Query(default=None),
    section: Section | None = Query(default=None),
    q: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[EventListItem]:
    """Sections are queries over show data, not a stored trending score."""
    return await service.list_events(session, type, city, section, q)


@public_router.get(
    "/events/{event_id}", response_model=EventListItem, summary="One event"
)
async def get_event(
    event_id: int, session: AsyncSession = Depends(get_session)
) -> EventListItem:
    """Errors:
      * `NOT_FOUND` (404) -- no such event.
    """
    return await service.get_event(session, event_id)


@public_router.get(
    "/events/{event_id}/showtimes",
    response_model=list[VenueShowtimes],
    summary="Showtimes grouped by venue",
)
async def get_showtimes(
    event_id: int,
    date_: date | None = Query(default=None, alias="date"),
    language: str | None = Query(default=None),
    format: ShowFormat | None = Query(default=None),
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[VenueShowtimes]:
    """Only scheduled shows still in the future.

    Errors:
      * `NOT_FOUND` (404) -- no such event.
    """
    return await service.get_showtimes(session, event_id, date_, language, format, city)


@public_router.get("/shows/{show_id}", response_model=ShowDetail, summary="One show")
async def get_show(
    show_id: int, session: AsyncSession = Depends(get_session)
) -> ShowDetail:
    """Errors:
      * `NOT_FOUND` (404) -- no such show.
    """
    return await service.get_show(session, show_id)
