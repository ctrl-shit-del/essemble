"""Events, shows, scheduling rules and public catalog reads."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import conflict, forbidden, not_found, validation_error
from app.models import (
    BookingPolicy,
    Event,
    EventType,
    Screen,
    SeatCategory,
    Show,
    ShowCategoryPrice,
    ShowFormat,
    ShowStatus,
    UserAccount,
    Venue,
)
from app.schemas.catalog import (
    CategoryPrice,
    EventCreate,
    EventListItem,
    EventResponse,
    Section,
    ShowCreate,
    ShowDetail,
    ShowResponse,
    ShowtimeItem,
    ShowUpdate,
    VenueShowtimes,
)


# ---------------------------------------------------------------- scheduling


def effective_runtime(event: Event) -> int:
    return event.runtime_min or settings.default_event_runtime_min


async def assert_starts_in_future(session: AsyncSession, starts_at: datetime) -> None:
    """Compare against the database clock, never the application's."""
    is_future = await session.scalar(
        text("SELECT CAST(:starts_at AS timestamptz) > now()"), {"starts_at": starts_at}
    )
    if not is_future:
        raise validation_error(
            "starts_at must be in the future.", [{"field": "starts_at"}]
        )


async def assert_slot_free(
    session: AsyncSession,
    screen_id: int,
    starts_at: datetime,
    runtime_min: int,
    exclude_show_id: int | None = None,
) -> None:
    """No other scheduled show may overlap [start, start + runtime + buffer).

    This is a cross-row invariant, so it cannot be a CHECK constraint. It has
    to be re-run at every point a show can come into existence -- including
    venue-request approval, where the slot may have been taken while the
    request sat pending.
    """
    buffer = settings.show_buffer_minutes
    clash = (
        await session.execute(
            text(
                """
                SELECT s.id, s.starts_at, e.title
                  FROM show s
                  JOIN event e ON e.id = s.event_id
                 WHERE s.screen_id = :screen_id
                   AND s.status = 'scheduled'
                   AND (CAST(:exclude_id AS bigint) IS NULL OR s.id <> :exclude_id)
                   -- asyncpg sends :starts_at untyped; without the cast
                   -- Postgres resolves "unknown + interval" to interval and
                   -- then refuses to compare it against a timestamptz.
                   AND s.starts_at
                       < CAST(:starts_at AS timestamptz)
                         + make_interval(mins => :proposed_len)
                   AND s.starts_at
                       + make_interval(
                           mins => coalesce(e.runtime_min, :default_runtime) + :buffer
                         ) > CAST(:starts_at AS timestamptz)
                 ORDER BY s.starts_at
                 LIMIT 1
                """
            ),
            {
                "screen_id": screen_id,
                "exclude_id": exclude_show_id,
                "starts_at": starts_at,
                "proposed_len": runtime_min + buffer,
                "default_runtime": settings.default_event_runtime_min,
                "buffer": buffer,
            },
        )
    ).first()

    if clash is not None:
        raise conflict(
            "Another show occupies this screen at that time "
            f"(including the {buffer}-minute changeover buffer).",
            {
                "conflicting_show_id": clash[0],
                "conflicting_starts_at": clash[1].isoformat(),
                "conflicting_title": clash[2],
            },
        )


async def resolve_pricing(
    session: AsyncSession, screen_id: int, pricing: dict[int, Decimal]
) -> dict[int, Decimal]:
    """Every seat_category on the screen must be priced, and nothing else.

    Re-derived from the screen's CURRENT categories each time it is called --
    a layout may have been regenerated since the prices were first submitted.
    """
    category_ids = set(
        (
            await session.scalars(
                select(SeatCategory.id).where(SeatCategory.screen_id == screen_id)
            )
        ).all()
    )
    if not category_ids:
        raise validation_error(
            "That screen has no seat layout yet; generate one before scheduling."
        )

    given = set(pricing)
    missing = sorted(category_ids - given)
    unknown = sorted(given - category_ids)
    if missing or unknown:
        raise validation_error(
            "pricing must name every seat category on the screen, and only those.",
            {"missing_category_ids": missing, "unknown_category_ids": unknown},
        )
    return pricing


# -------------------------------------------------------------------- events


async def create_event(
    session: AsyncSession, organiser: UserAccount, payload: EventCreate
) -> EventResponse:
    event = Event(organiser_id=organiser.id, **payload.model_dump())
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return EventResponse.model_validate(event)


async def load_own_event(
    session: AsyncSession, event_id: int, organiser: UserAccount
) -> Event:
    event = await session.scalar(select(Event).where(Event.id == event_id))
    if event is None or event.organiser_id != organiser.id:
        raise forbidden("That event does not belong to you.")
    return event


async def load_own_show(
    session: AsyncSession, show_id: int, organiser: UserAccount
) -> Show:
    show = await session.scalar(select(Show).where(Show.id == show_id))
    if show is None or show.organiser_id != organiser.id:
        raise forbidden("That show does not belong to you.")
    return show


async def load_screen_with_venue(
    session: AsyncSession, screen_id: int
) -> tuple[Screen, Venue]:
    row = (
        await session.execute(
            select(Screen, Venue)
            .join(Venue, Venue.id == Screen.venue_id)
            .where(Screen.id == screen_id)
        )
    ).first()
    if row is None:
        # Screens are public catalog surface; existence is not a secret here.
        raise not_found("No such screen.")
    return row[0], row[1]


# --------------------------------------------------------------------- shows


async def write_show(
    session: AsyncSession,
    organiser_id: int,
    payload_event_id: int,
    screen_id: int,
    starts_at: datetime,
    language: str,
    format_: ShowFormat | None,
    pricing: dict[int, Decimal],
) -> Show:
    """Insert a show and its frozen per-category prices. Caller commits."""
    show = Show(
        event_id=payload_event_id,
        screen_id=screen_id,
        organiser_id=organiser_id,
        starts_at=starts_at,
        language=language,
        format=format_,
        status=ShowStatus.SCHEDULED,
    )
    session.add(show)
    await session.flush()
    session.add_all(
        ShowCategoryPrice(show_id=show.id, category_id=category_id, price=price)
        for category_id, price in pricing.items()
    )
    return show


async def create_show(
    session: AsyncSession, organiser: UserAccount, payload: ShowCreate
) -> ShowResponse:
    """The 'open' venue path. Request-policy venues are handled elsewhere."""
    event = await load_own_event(session, payload.event_id, organiser)
    screen, _venue = await load_screen_with_venue(session, payload.screen_id)

    pricing = await resolve_pricing(session, screen.id, payload.pricing)
    await assert_starts_in_future(session, payload.starts_at)
    await assert_slot_free(
        session, screen.id, payload.starts_at, effective_runtime(event)
    )

    show = await write_show(
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
    return ShowResponse.model_validate(show)


async def list_own_shows(
    session: AsyncSession, organiser: UserAccount
) -> list[ShowResponse]:
    shows = (
        await session.scalars(
            select(Show)
            .where(Show.organiser_id == organiser.id)
            .order_by(Show.starts_at)
        )
    ).all()
    return [ShowResponse.model_validate(s) for s in shows]


async def update_show(
    session: AsyncSession, organiser: UserAccount, show_id: int, payload: ShowUpdate
) -> ShowResponse:
    show = await load_own_show(session, show_id, organiser)
    event = await session.scalar(select(Event).where(Event.id == show.event_id))
    assert event is not None  # FK guarantees it

    if payload.starts_at is not None and payload.starts_at != show.starts_at:
        await assert_starts_in_future(session, payload.starts_at)
        await assert_slot_free(
            session,
            show.screen_id,
            payload.starts_at,
            effective_runtime(event),
            exclude_show_id=show.id,
        )
        show.starts_at = payload.starts_at

    if payload.language is not None:
        show.language = payload.language
    if payload.format is not None:
        show.format = payload.format
    if payload.status is not None:
        show.status = payload.status

    if payload.pricing is not None:
        pricing = await resolve_pricing(session, show.screen_id, payload.pricing)
        existing = (
            await session.scalars(
                select(ShowCategoryPrice).where(ShowCategoryPrice.show_id == show.id)
            )
        ).all()
        by_category = {row.category_id: row for row in existing}
        for category_id, price in pricing.items():
            if category_id in by_category:
                # Re-pricing a show never rewrites booking_seat.price, which is
                # frozen at confirmation time.
                by_category[category_id].price = price
            else:
                session.add(
                    ShowCategoryPrice(
                        show_id=show.id, category_id=category_id, price=price
                    )
                )

    await session.commit()
    await session.refresh(show)
    return ShowResponse.model_validate(show)


# ------------------------------------------------------------ public catalog


async def _event_rollups(
    session: AsyncSession, event_ids: list[int]
) -> dict[int, dict]:
    """Show-derived numbers for a set of events. No stored popularity."""
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            text(
                """
                SELECT s.event_id,
                       count(*)                       AS upcoming_shows,
                       min(s.starts_at)               AS next_show_at,
                       array_agg(DISTINCT v.city)     AS cities,
                       min(p.price)                   AS from_price
                  FROM show s
                  JOIN screen sc ON sc.id = s.screen_id
                  JOIN venue  v  ON v.id  = sc.venue_id
                  LEFT JOIN show_category_price p ON p.show_id = s.id
                 WHERE s.event_id = ANY(:ids)
                   AND s.status = 'scheduled'
                   AND s.starts_at > now()
                 GROUP BY s.event_id
                """
            ),
            {"ids": event_ids},
        )
    ).mappings()
    return {row["event_id"]: dict(row) for row in rows}


async def list_events(
    session: AsyncSession,
    event_type: EventType | None = None,
    city: str | None = None,
    section: Section | None = None,
    q: str | None = None,
) -> list[EventListItem]:
    """Browse the catalog.

    Sections are plain queries over show data -- there is no stored trending
    score anywhere in this system:
      now_showing -- has a scheduled show inside the next 7 days
      upcoming    -- first scheduled show is beyond 7 days, or it has a future
                     release_date and nothing scheduled yet
      live        -- event_type = 'live'
      popular     -- ordered by confirmed bookings across its shows
    """
    clauses = ["TRUE"]
    params: dict[str, object] = {}

    if event_type is not None:
        clauses.append("CAST(e.event_type AS text) = :event_type")
        params["event_type"] = event_type.value
    if q:
        clauses.append("(e.title ILIKE :q OR coalesce(e.artist_name,'') ILIKE :q)")
        params["q"] = f"%{q}%"
    if city:
        clauses.append(
            """EXISTS (SELECT 1 FROM show s
                         JOIN screen sc ON sc.id = s.screen_id
                         JOIN venue v ON v.id = sc.venue_id
                        WHERE s.event_id = e.id AND s.status = 'scheduled'
                          AND s.starts_at > now() AND v.city ILIKE :city)"""
        )
        params["city"] = city

    order = "e.created_at DESC"
    if section == "live":
        clauses.append("e.event_type = 'live'")
    elif section == "now_showing":
        clauses.append(
            """EXISTS (SELECT 1 FROM show s WHERE s.event_id = e.id
                        AND s.status = 'scheduled'
                        AND s.starts_at BETWEEN now() AND now() + interval '7 days')"""
        )
        order = "e.title"
    elif section == "upcoming":
        clauses.append(
            """(
                 (SELECT min(s.starts_at) FROM show s
                   WHERE s.event_id = e.id AND s.status = 'scheduled'
                     AND s.starts_at > now()) > now() + interval '7 days'
                 OR (
                   e.release_date > current_date
                   AND NOT EXISTS (SELECT 1 FROM show s
                                    WHERE s.event_id = e.id
                                      AND s.status = 'scheduled'
                                      AND s.starts_at > now())
                 )
               )"""
        )
        order = "coalesce(e.release_date, current_date)"
    elif section == "popular":
        order = """(
            SELECT count(*) FROM booking b
              JOIN show s ON s.id = b.show_id
             WHERE s.event_id = e.id AND b.status = 'confirmed'
        ) DESC, e.created_at DESC"""

    events = (
        await session.scalars(
            select(Event)
            .from_statement(
                text(
                    f"SELECT e.* FROM event e WHERE {' AND '.join(clauses)} "
                    f"ORDER BY {order} LIMIT 100"
                ).bindparams(**params)
            )
        )
    ).all()

    rollups = await _event_rollups(session, [e.id for e in events])
    items: list[EventListItem] = []
    for event in events:
        roll = rollups.get(event.id, {})
        items.append(
            EventListItem(
                **EventResponse.model_validate(event).model_dump(),
                upcoming_shows=roll.get("upcoming_shows", 0),
                next_show_at=roll.get("next_show_at"),
                cities=sorted(roll.get("cities") or []),
                from_price=roll.get("from_price"),
            )
        )
    return items


async def get_event(session: AsyncSession, event_id: int) -> EventListItem:
    event = await session.scalar(select(Event).where(Event.id == event_id))
    if event is None:
        raise not_found("No such event.")
    roll = (await _event_rollups(session, [event.id])).get(event.id, {})
    return EventListItem(
        **EventResponse.model_validate(event).model_dump(),
        upcoming_shows=roll.get("upcoming_shows", 0),
        next_show_at=roll.get("next_show_at"),
        cities=sorted(roll.get("cities") or []),
        from_price=roll.get("from_price"),
    )


async def get_showtimes(
    session: AsyncSession,
    event_id: int,
    on: date | None = None,
    language: str | None = None,
    format_: ShowFormat | None = None,
    city: str | None = None,
) -> list[VenueShowtimes]:
    exists_event = await session.scalar(select(Event.id).where(Event.id == event_id))
    if exists_event is None:
        raise not_found("No such event.")

    rows = (
        await session.execute(
            text(
                """
                SELECT s.id AS show_id, s.starts_at, s.language, s.format,
                       v.id AS venue_id, v.name AS venue_name, v.city, v.address,
                       sc.id AS screen_id, sc.name AS screen_name,
                       (SELECT min(p.price) FROM show_category_price p
                         WHERE p.show_id = s.id) AS from_price
                  FROM show s
                  JOIN screen sc ON sc.id = s.screen_id
                  JOIN venue  v  ON v.id  = sc.venue_id
                 WHERE s.event_id = :event_id
                   AND s.status = 'scheduled'
                   AND s.starts_at > now()
                   AND (CAST(:on AS date) IS NULL OR CAST(s.starts_at AS date) = :on)
                   -- Each optional filter is cast explicitly: a bare
                   -- "$n IS NULL" leaves asyncpg with no type to infer.
                   AND (CAST(:lang AS text) IS NULL OR s.language = :lang)
                   AND (CAST(:fmt  AS text) IS NULL OR CAST(s.format AS text) = :fmt)
                   AND (CAST(:city AS text) IS NULL OR v.city ILIKE :city)
                 ORDER BY v.name, s.starts_at
                """
            ),
            {
                "event_id": event_id,
                "on": on,
                "lang": language,
                "fmt": format_.value if format_ else None,
                "city": city,
            },
        )
    ).mappings()

    grouped: dict[int, VenueShowtimes] = {}
    for row in rows:
        venue = grouped.get(row["venue_id"])
        if venue is None:
            venue = VenueShowtimes(
                venue_id=row["venue_id"],
                venue_name=row["venue_name"],
                city=row["city"],
                address=row["address"],
                shows=[],
            )
            grouped[row["venue_id"]] = venue
        venue.shows.append(
            ShowtimeItem(
                show_id=row["show_id"],
                starts_at=row["starts_at"],
                language=row["language"],
                format=row["format"],
                venue_id=row["venue_id"],
                venue_name=row["venue_name"],
                city=row["city"],
                screen_id=row["screen_id"],
                screen_name=row["screen_name"],
                from_price=row["from_price"],
            )
        )
    return list(grouped.values())


async def get_show(session: AsyncSession, show_id: int) -> ShowDetail:
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
    show, event, screen, venue = row

    prices = (
        await session.execute(
            select(ShowCategoryPrice, SeatCategory)
            .join(SeatCategory, SeatCategory.id == ShowCategoryPrice.category_id)
            .where(ShowCategoryPrice.show_id == show.id)
            .order_by(SeatCategory.rank)
        )
    ).all()

    return ShowDetail(
        **ShowResponse.model_validate(show).model_dump(),
        event=EventResponse.model_validate(event),
        venue_id=venue.id,
        venue_name=venue.name,
        city=venue.city,
        screen_name=screen.name,
        total_seats=screen.total_seats,
        pricing=[
            CategoryPrice(
                category_id=category.id,
                name=category.name,
                rank=category.rank,
                price=price.price,
            )
            for price, category in prices
        ],
    )


def is_request_policy(venue: Venue) -> bool:
    return venue.booking_policy is BookingPolicy.REQUEST


def default_request_window(starts_at: datetime, runtime_min: int) -> datetime:
    """A single-show request still needs an end to its window."""
    return starts_at + timedelta(minutes=runtime_min + settings.show_buffer_minutes)
