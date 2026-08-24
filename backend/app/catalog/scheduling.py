"""The one entry point for scheduling a show.

Kept separate from catalog.service so that the venue-request module can import
catalog.service without a cycle: this module depends on both, neither depends
on this.
"""

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import service as catalog_service
from app.models import UserAccount
from app.schemas.catalog import ShowCreate, ShowResponse
from app.schemas.venue_request import ShowScheduleResult
from app.venues import requests_service


async def schedule_show(
    session: AsyncSession, organiser: UserAccount, payload: ShowCreate
) -> tuple[ShowScheduleResult, int]:
    """Create a show, or a pending request against a 'request' venue.

    Returns (result, http_status): 201 for a created show, 202 for a request.
    Both paths run the same validation first, so an organiser gets told about a
    clashing slot or bad pricing immediately rather than after an admin has
    spent a day sitting on the request.
    """
    event = await catalog_service.load_own_event(session, payload.event_id, organiser)
    screen, venue = await catalog_service.load_screen_with_venue(
        session, payload.screen_id
    )

    pricing = await catalog_service.resolve_pricing(session, screen.id, payload.pricing)
    await catalog_service.assert_starts_in_future(session, payload.starts_at)
    await catalog_service.assert_slot_free(
        session,
        screen.id,
        payload.starts_at,
        catalog_service.effective_runtime(event),
    )

    if catalog_service.is_request_policy(venue):
        # No `show` row. An unapproved show must not exist in that table at
        # all, so that no catalog query can leak one by missing a filter.
        request = await requests_service.create_request(
            session,
            organiser,
            event,
            screen,
            venue,
            payload.starts_at,
            payload.language,
            payload.format,
            pricing,
        )
        await session.commit()
        await session.refresh(request)
        return (
            ShowScheduleResult(
                status="pending_approval",
                venue_request=await requests_service.hydrate(session, request),
            ),
            status.HTTP_202_ACCEPTED,
        )

    show = await catalog_service.write_show(
        session,
        organiser.id,
        event.id,
        screen.id,
        payload.starts_at,
        payload.language,
        payload.format,
        pricing,
    )
    await session.commit()
    await session.refresh(show)
    return (
        ShowScheduleResult(status="created", show=ShowResponse.model_validate(show)),
        status.HTTP_201_CREATED,
    )
