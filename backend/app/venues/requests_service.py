"""Venue slot requests: creation, listing, and the approval transaction."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import service as catalog_service
from app.core.errors import conflict, forbidden
from app.models import (
    Event,
    Screen,
    ShowFormat,
    UserAccount,
    Venue,
    VenueRequest,
    VenueRequestState,
)
from app.schemas.catalog import ShowResponse
from app.schemas.venue_request import (
    DecisionRequest,
    DecisionResponse,
    VenueRequestResponse,
)


def pricing_to_json(pricing: dict[int, Decimal]) -> dict[str, str]:
    """{category_id: Decimal} -> {"<id>": "<decimal string>"}.

    Strings on both sides of the pair: JSON numbers would go through float and
    quietly lose the last paisa.
    """
    return {str(category_id): str(price) for category_id, price in pricing.items()}


def pricing_from_json(stored: dict[str, str]) -> dict[int, Decimal]:
    return {int(key): Decimal(str(value)) for key, value in stored.items()}


async def create_request(
    session: AsyncSession,
    organiser: UserAccount,
    event: Event,
    screen: Screen,
    venue: Venue,
    starts_at: datetime,
    language: str,
    format_: ShowFormat | None,
    pricing: dict[int, Decimal],
) -> VenueRequest:
    """Record a pending request. Caller commits. No `show` row is written."""
    runtime = catalog_service.effective_runtime(event)
    request = VenueRequest(
        organiser_id=organiser.id,
        venue_id=venue.id,
        screen_id=screen.id,
        event_id=event.id,
        starts_at=starts_at,
        ends_at=catalog_service.default_request_window(starts_at, runtime),
        shows_per_day=1,
        language=language,
        format=format_,
        proposed_pricing=pricing_to_json(pricing),
        state=VenueRequestState.PENDING,
    )
    session.add(request)
    await session.flush()
    return request


async def _hydrate(session: AsyncSession, request: VenueRequest) -> VenueRequestResponse:
    row = (
        await session.execute(
            select(Venue.name, Screen.name, Event.title)
            .select_from(VenueRequest)
            .join(Venue, Venue.id == VenueRequest.venue_id)
            .join(Screen, Screen.id == VenueRequest.screen_id)
            .join(Event, Event.id == VenueRequest.event_id)
            .where(VenueRequest.id == request.id)
        )
    ).first()
    venue_name, screen_name, event_title = row if row else ("", "", "")
    return VenueRequestResponse(
        id=request.id,
        organiser_id=request.organiser_id,
        venue_id=request.venue_id,
        venue_name=venue_name,
        screen_id=request.screen_id,
        screen_name=screen_name,
        event_id=request.event_id,
        event_title=event_title,
        starts_at=request.starts_at,
        ends_at=request.ends_at,
        shows_per_day=request.shows_per_day,
        expected_audience=request.expected_audience,
        language=request.language,
        format=request.format,
        proposed_pricing=pricing_from_json(request.proposed_pricing),
        state=request.state,
        admin_message=request.admin_message,
        created_at=request.created_at,
        decided_at=request.decided_at,
    )


async def hydrate(session: AsyncSession, request: VenueRequest) -> VenueRequestResponse:
    return await _hydrate(session, request)


async def list_for_organiser(
    session: AsyncSession, organiser: UserAccount
) -> list[VenueRequestResponse]:
    requests = (
        await session.scalars(
            select(VenueRequest)
            .where(VenueRequest.organiser_id == organiser.id)
            .order_by(VenueRequest.created_at.desc())
        )
    ).all()
    return [await _hydrate(session, r) for r in requests]


async def list_for_admin(
    session: AsyncSession,
    admin: UserAccount,
    state: VenueRequestState | None = None,
) -> list[VenueRequestResponse]:
    """Only requests against venues this admin owns.

    Scoped by the join, not by a filter applied afterwards -- an admin must
    never be able to read the queue of another admin's venue.
    """
    query = (
        select(VenueRequest)
        .join(Venue, Venue.id == VenueRequest.venue_id)
        .where(Venue.admin_id == admin.id)
        .order_by(VenueRequest.created_at.desc())
    )
    if state is not None:
        query = query.where(VenueRequest.state == state)
    requests = (await session.scalars(query)).all()
    return [await _hydrate(session, r) for r in requests]


async def load_owned_request(
    session: AsyncSession, request_id: int, admin: UserAccount
) -> tuple[VenueRequest, Venue]:
    """request -> venue -> admin_id, or 403."""
    row = (
        await session.execute(
            select(VenueRequest, Venue)
            .join(Venue, Venue.id == VenueRequest.venue_id)
            .where(VenueRequest.id == request_id)
        )
    ).first()
    if row is None or row[1].admin_id != admin.id:
        raise forbidden("That venue request does not belong to your venues.")
    return row[0], row[1]


async def decide(
    session: AsyncSession,
    admin: UserAccount,
    request_id: int,
    payload: DecisionRequest,
) -> DecisionResponse:
    """Approve or reject, in one transaction.

    Approval is the only moment the scheduling constraint is real. Between
    submission and this call the slot may have been taken through the normal
    path, and two pending requests for the same slot can both arrive here --
    so the overlap check runs again, against live data, right before the show
    is written.
    """
    request, _venue = await load_owned_request(session, request_id, admin)

    if request.state is not VenueRequestState.PENDING:
        raise conflict(
            f"This request was already {request.state.value}.",
            {"state": request.state.value},
        )

    show: ShowResponse | None = None

    if payload.decision == "approve":
        event = await session.scalar(
            select(Event).where(Event.id == request.event_id)
        )
        if event is None:
            raise conflict("The event behind this request no longer exists.")

        # 1. The slot may be gone. Cross-row invariant, so no CHECK can hold it.
        await catalog_service.assert_starts_in_future(session, request.starts_at)
        await catalog_service.assert_slot_free(
            session,
            request.screen_id,
            request.starts_at,
            catalog_service.effective_runtime(event),
        )

        # 2. The layout may have been regenerated since the request was filed,
        #    which would have replaced every seat_category id it names.
        pricing = await catalog_service.resolve_pricing(
            session, request.screen_id, pricing_from_json(request.proposed_pricing)
        )

        # 3. Only now does the show come into existence.
        created = await catalog_service.write_show(
            session,
            request.organiser_id,
            request.event_id,
            request.screen_id,
            request.starts_at,
            request.language,
            request.format,
            pricing,
        )
        show = ShowResponse.model_validate(created)
        request.state = VenueRequestState.APPROVED
    else:
        request.state = VenueRequestState.REJECTED

    # 4. Decision metadata, same transaction as the show.
    request.admin_message = payload.admin_message
    await session.execute(
        text("UPDATE venue_request SET decided_at = now() WHERE id = :id"),
        {"id": request.id},
    )
    await session.commit()
    await session.refresh(request)

    return DecisionResponse(request=await _hydrate(session, request), show=show)
