"""Seed a demo world. Idempotent.

Run:
    python -m scripts.seed              # create or top up
    python -m scripts.seed --reset      # wipe application tables first

IDEMPOTENCY
Every object is looked up by a natural key -- an email, a (venue, screen)
name, an (event, screen, start time) triple -- and created only when absent.
Re-running changes nothing and duplicates nothing.

Showtimes are anchored to TODAY's date at fixed clock times rather than to
`now() + n hours`. That is what makes the future shows idempotent: running
twice in one day is a no-op. Running on a later day adds that day's window,
which is the behaviour a demo database wants -- it never goes stale, and it
still never duplicates, because the (event, screen, starts_at) key differs.

The reset path is guarded. This script is expected to live alongside a hosted
demo database, and `--reset` against it would be unrecoverable.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory, engine
from app.core.security import hash_password, new_reference, qr_signature
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    BookingPolicy,
    ClaimState,
    Event,
    EventType,
    HolderType,
    Screen,
    Seat,
    SeatCategory,
    SeatClaim,
    Show,
    ShowCategoryPrice,
    ShowFormat,
    UserAccount,
    UserRole,
    Venue,
    VenueRequest,
    VenueRequestState,
    WaitlistEntry,
    WaitlistEntryState,
)
from app.schemas.venue import LayoutCategory, LayoutRequest
from app.venues.layout import generate_seats

PASSWORD = "essemble123"

#: Tables the reset path clears, child-first. `alembic_version` is
#: deliberately absent: wiping data must never look like un-migrating.
APPLICATION_TABLES = (
    "booking_seat, booking, seat_claim, waitlist_offer, waitlist_entry, "
    "outbox, idempotency_key, show_category_price, show, venue_request, "
    "event, seat, seat_category, screen, venue, user_account"
)

#: Hosts where --reset is allowed without an explicit override. Anything else
#: -- a managed provider, anything with a real hostname -- has to be asked for
#: by name, because losing a hosted demo database is not recoverable.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", "db", "postgres"}


# --------------------------------------------------------------- the world


@dataclass(frozen=True)
class ScreenSpec:
    name: str
    rows: int
    seats_per_row: int
    aisles: list[int]
    categories: list[tuple[str, int, str, str]]  # name, rank, row_from, row_to


#: Three categories on the two larger halls, two on the small one. Row ranges
#: cover every row exactly once, which the layout generator enforces.
LARGE_12x18 = ScreenSpec(
    name="Audi 1 - IMAX",
    rows=12,
    seats_per_row=18,
    aisles=[3, 15],
    categories=[
        ("VIP", 1, "A", "B"),
        ("Premium", 2, "C", "G"),
        ("Standard", 3, "H", "L"),
    ],
)
LARGE_10x14 = ScreenSpec(
    name="Audi 2",
    rows=10,
    seats_per_row=14,
    aisles=[3, 11],
    categories=[
        ("VIP", 1, "A", "B"),
        ("Premium", 2, "C", "F"),
        ("Standard", 3, "G", "J"),
    ],
)
SMALL_8x12 = ScreenSpec(
    name="Audi 3",
    rows=8,
    seats_per_row=12,
    aisles=[6],
    categories=[
        ("Premium", 1, "A", "C"),
        ("Standard", 2, "D", "H"),
    ],
)
LUXE_10x14 = ScreenSpec(
    name="Screen 1 - Gold",
    rows=10,
    seats_per_row=14,
    aisles=[3, 11],
    categories=[
        ("VIP", 1, "A", "B"),
        ("Premium", 2, "C", "F"),
        ("Standard", 3, "G", "J"),
    ],
)
LUXE_8x12 = ScreenSpec(
    name="Screen 2",
    rows=8,
    seats_per_row=12,
    aisles=[6],
    categories=[
        ("Premium", 1, "A", "C"),
        ("Standard", 2, "D", "H"),
    ],
)

#: Per-category pricing, in rupees. Premium sits in the 300-500 band the
#: seeded history is specified to use.
PRICING = {"VIP": Decimal("650.00"), "Premium": Decimal("420.00"),
           "Standard": Decimal("250.00")}
LUXE_PRICING = {"VIP": Decimal("900.00"), "Premium": Decimal("550.00"),
                "Standard": Decimal("350.00")}


def poster(slug: str) -> str:
    """A stable public placeholder. Seeded by slug, so it never changes."""
    return f"https://picsum.photos/seed/{slug}-poster/500/750"


def backdrop(slug: str) -> str:
    return f"https://picsum.photos/seed/{slug}-backdrop/1280/720"


@dataclass(frozen=True)
class EventSpec:
    slug: str
    event_type: EventType
    title: str
    description: str
    runtime_min: int
    genres: list[str]
    certification: str | None = None
    artist_name: str | None = None


EVENTS = [
    EventSpec(
        slug="nebula-drift",
        event_type=EventType.MOVIE,
        title="Nebula Drift",
        description=(
            "A salvage crew wakes from cryosleep to find their ship four "
            "hundred years off course and no longer alone aboard."
        ),
        runtime_min=148,
        genres=["Sci-Fi", "Adventure"],
        certification="UA",
    ),
    EventSpec(
        slug="quantum-hour",
        event_type=EventType.MOVIE,
        title="The Quantum Hour",
        description=(
            "A physicist relives the same sixty minutes until she works out "
            "which of her colleagues is not who they claim to be."
        ),
        runtime_min=118,
        genres=["Sci-Fi", "Thriller"],
        certification="UA",
    ),
    EventSpec(
        slug="kaaval-nagaram",
        event_type=EventType.MOVIE,
        title="Kaaval Nagaram",
        description=(
            "A night-shift constable in North Chennai has eight hours to "
            "return a stolen ledger before the city wakes up to a war."
        ),
        runtime_min=152,
        genres=["Action", "Thriller"],
        certification="A",
    ),
    EventSpec(
        slug="long-monsoon",
        event_type=EventType.MOVIE,
        title="The Long Monsoon",
        description=(
            "Two strangers share a stalled train carriage through a week of "
            "rain, and discover they have met before."
        ),
        runtime_min=127,
        genres=["Drama", "Romance"],
        certification="U",
    ),
    EventSpec(
        slug="under-review",
        event_type=EventType.LIVE,
        title="Under Review - Live Stand-Up",
        description=(
            "Ninety minutes of new material on landlords, airports and the "
            "quiet indignity of being asked to rate your experience."
        ),
        runtime_min=90,
        genres=["Comedy", "Stand-Up"],
        artist_name="Aakash Mehta",
    ),
    EventSpec(
        slug="carnatic-electric",
        event_type=EventType.LIVE,
        title="Carnatic Electric",
        description=(
            "A seven-piece band setting classical Carnatic ragas against a "
            "live electronic rhythm section."
        ),
        runtime_min=120,
        genres=["Music", "Concert"],
        artist_name="Agam",
    ),
]

#: Every language/format pair the catalog advertises. The seeder guarantees at
#: least one live show for each, so the language+format filter modal always
#: has something to show rather than rendering an empty list on a fresh
#: database.
LANGUAGE_FORMATS: list[tuple[str, ShowFormat | None]] = [
    ("English", ShowFormat.TWO_D),
    ("English", ShowFormat.THREE_D),
    ("English", ShowFormat.IMAX),
    ("English", ShowFormat.EPIQ_3D),
    ("Tamil", ShowFormat.TWO_D),
    ("Tamil", ShowFormat.THREE_D),
    ("Hindi", ShowFormat.TWO_D),
]


# --------------------------------------------------------------- utilities


@dataclass
class Summary:
    """What the run created, and where the demo targets ended up."""

    created: dict[str, int] = field(default_factory=dict)
    reused: dict[str, int] = field(default_factory=dict)
    targets: dict[str, str] = field(default_factory=dict)

    def note(self, kind: str, was_created: bool) -> None:
        bucket = self.created if was_created else self.reused
        bucket[kind] = bucket.get(kind, 0) + 1


IST = timezone(timedelta(hours=5, minutes=30))


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """A showtime on `day`, expressed in IST and stored as UTC.

    Times are wall-clock in the venue's own timezone; storing them as UTC
    keeps every comparison in the database honest.
    """
    return datetime.combine(day, time(hour, minute), tzinfo=IST).astimezone(
        timezone.utc
    )


async def get_or_create_user(
    session: AsyncSession, summary: Summary, email: str, name: str, role: UserRole
) -> UserAccount:
    user = await session.scalar(
        select(UserAccount).where(UserAccount.email == email)
    )
    if user is not None:
        summary.note("users", False)
        return user
    user = UserAccount(
        email=email,
        name=name,
        role=role,
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.flush()
    summary.note("users", True)
    return user


async def get_or_create_venue(
    session: AsyncSession,
    summary: Summary,
    admin: UserAccount,
    name: str,
    city: str,
    address: str,
    policy: BookingPolicy,
) -> Venue:
    venue = await session.scalar(
        select(Venue).where(Venue.name == name, Venue.city == city)
    )
    if venue is not None:
        summary.note("venues", False)
        return venue
    venue = Venue(
        admin_id=admin.id,
        name=name,
        city=city,
        address=address,
        booking_policy=policy,
    )
    session.add(venue)
    await session.flush()
    summary.note("venues", True)
    return venue


async def get_or_create_screen(
    session: AsyncSession, summary: Summary, venue: Venue, spec: ScreenSpec
) -> Screen:
    """Create the screen and, if it has no seats yet, lay it out.

    Layout runs through the real generator -- the same `generate_seats` the
    admin API calls -- rather than hand-written seat rows, so aisle offsets
    and category row ranges are produced by the code under test, not by a
    second implementation that could drift from it.
    """
    screen = await session.scalar(
        select(Screen).where(Screen.venue_id == venue.id, Screen.name == spec.name)
    )
    created = screen is None
    if screen is None:
        screen = Screen(venue_id=venue.id, name=spec.name)
        session.add(screen)
        await session.flush()
    summary.note("screens", created)

    seat_count = await session.scalar(
        select(func.count()).select_from(Seat).where(Seat.screen_id == screen.id)
    )
    if seat_count:
        return screen

    request = LayoutRequest(
        rows=spec.rows,
        seats_per_row=spec.seats_per_row,
        aisle_after_columns=spec.aisles,
        categories=[
            LayoutCategory(name=n, rank=r, row_from=f, row_to=t)
            for n, r, f, t in spec.categories
        ],
    )
    generated = generate_seats(
        request.rows,
        request.seats_per_row,
        request.aisle_after_columns,
        request.categories,
    )

    categories = {
        name: SeatCategory(screen_id=screen.id, name=name, rank=rank)
        for name, rank, _f, _t in spec.categories
    }
    session.add_all(categories.values())
    await session.flush()

    session.add_all(
        Seat(
            screen_id=screen.id,
            row_label=seat.row_label,
            seat_number=seat.seat_number,
            category_id=categories[seat.category_name].id,
            x=seat.x,
            y=seat.y,
        )
        for seat in generated
    )
    screen.total_seats = len(generated)
    await session.flush()
    summary.created["seats"] = summary.created.get("seats", 0) + len(generated)
    return screen


async def get_or_create_event(
    session: AsyncSession, summary: Summary, organiser: UserAccount, spec: EventSpec
) -> Event:
    event = await session.scalar(
        select(Event).where(
            Event.organiser_id == organiser.id, Event.title == spec.title
        )
    )
    if event is not None:
        summary.note("events", False)
        return event
    event = Event(
        organiser_id=organiser.id,
        event_type=spec.event_type,
        title=spec.title,
        description=spec.description,
        poster_url=poster(spec.slug),
        backdrop_url=backdrop(spec.slug),
        runtime_min=spec.runtime_min,
        certification=spec.certification,
        genres=spec.genres,
        artist_name=spec.artist_name,
        release_date=date.today() - timedelta(days=30),
    )
    session.add(event)
    await session.flush()
    summary.note("events", True)
    return event


async def categories_of(
    session: AsyncSession, screen_id: int
) -> dict[str, SeatCategory]:
    rows = (
        await session.scalars(
            select(SeatCategory)
            .where(SeatCategory.screen_id == screen_id)
            .order_by(SeatCategory.rank)
        )
    ).all()
    return {c.name: c for c in rows}


async def get_or_create_show(
    session: AsyncSession,
    summary: Summary,
    organiser: UserAccount,
    event: Event,
    screen: Screen,
    starts_at: datetime,
    language: str,
    show_format: ShowFormat | None,
    prices: dict[str, Decimal],
) -> Show:
    show = await session.scalar(
        select(Show).where(
            Show.event_id == event.id,
            Show.screen_id == screen.id,
            Show.starts_at == starts_at,
        )
    )
    if show is not None:
        summary.note("shows", False)
        return show

    show = Show(
        event_id=event.id,
        screen_id=screen.id,
        organiser_id=organiser.id,
        starts_at=starts_at,
        language=language,
        format=show_format,
    )
    session.add(show)
    await session.flush()

    for name, category in (await categories_of(session, screen.id)).items():
        session.add(
            ShowCategoryPrice(
                show_id=show.id, category_id=category.id, price=prices[name]
            )
        )
    await session.flush()
    summary.note("shows", True)
    return show


async def seats_in_category(
    session: AsyncSession, screen_id: int, category_id: int
) -> list[Seat]:
    return list(
        (
            await session.scalars(
                select(Seat)
                .where(Seat.screen_id == screen_id, Seat.category_id == category_id)
                .order_by(Seat.y, Seat.x)
            )
        ).all()
    )


async def unique_reference(session: AsyncSession) -> str:
    for _ in range(20):
        candidate = new_reference()
        clash = await session.scalar(
            select(Booking.id).where(Booking.reference == candidate)
        )
        if clash is None:
            return candidate
    raise RuntimeError("could not allocate a booking reference")


async def make_booking(
    session: AsyncSession,
    summary: Summary,
    user: UserAccount,
    show: Show,
    seats: list[Seat],
    category: SeatCategory,
    price: Decimal,
    booked_at: datetime,
) -> Booking | None:
    """A confirmed booking, written the way the API writes one.

    Real `seat_claim` rows in state 'booked' with no expiry, a `booking`, and
    one `booking_seat` per seat carrying the price paid. The recommendation
    logic and the seat map both read these tables directly, so fabricating
    only the `booking` row would leave the seat map showing them free.

    Returns None if any of the seats is already claimed for this show -- the
    partial unique index is the authority, and a re-run must not fight it.
    """
    taken = await session.scalar(
        select(func.count())
        .select_from(SeatClaim)
        .where(
            SeatClaim.show_id == show.id,
            SeatClaim.seat_id.in_([s.id for s in seats]),
            SeatClaim.state.in_([ClaimState.HELD, ClaimState.BOOKED]),
        )
    )
    if taken:
        summary.note("bookings", False)
        return None

    group: UUID = uuid4()
    reference = await unique_reference(session)

    for seat in seats:
        session.add(
            SeatClaim(
                show_id=show.id,
                seat_id=seat.id,
                hold_group_id=group,
                state=ClaimState.BOOKED,
                holder_type=HolderType.USER,
                holder_id=user.id,
                expires_at=None,
                created_at=booked_at,
            )
        )

    booking = Booking(
        reference=reference,
        show_id=show.id,
        user_id=user.id,
        hold_group_id=group,
        total_amount=price * len(seats),
        status=BookingStatus.CONFIRMED,
        qr_signature=qr_signature(reference),
        created_at=booked_at,
    )
    session.add(booking)
    await session.flush()

    for seat in seats:
        session.add(
            BookingSeat(
                booking_id=booking.id,
                seat_id=seat.id,
                category_id=category.id,
                price=price,
            )
        )
    await session.flush()
    summary.note("bookings", True)
    return booking


# ------------------------------------------------------------------- seed


async def seed(session: AsyncSession) -> Summary:
    summary = Summary()
    today = date.today()

    # --- users ------------------------------------------------------------
    admin = await get_or_create_user(
        session, summary, "admin@essemble.dev", "Priya Raghavan", UserRole.ADMIN
    )
    organiser = await get_or_create_user(
        session, summary, "organiser@essemble.dev", "Vikram Iyer", UserRole.ORGANISER
    )
    newcomer = await get_or_create_user(
        session, summary, "new@essemble.dev", "Ananya Nair", UserRole.CUSTOMER
    )
    regular = await get_or_create_user(
        session, summary, "regular@essemble.dev", "Rohan Desai", UserRole.CUSTOMER
    )
    # Filler bookers, so the near-sold-out show looks like a crowd rather than
    # one person buying twenty-seven seats. Kept obviously named.
    crowd = [
        await get_or_create_user(
            session, summary, f"crowd{i}@essemble.dev", f"Guest {i}", UserRole.CUSTOMER
        )
        for i in range(1, 7)
    ]

    # --- venues and screens ----------------------------------------------
    pvr = await get_or_create_venue(
        session, summary, admin,
        "PVR Marina", "Chennai",
        "2nd Floor, Marina Mall, Egattur, Chennai 603103",
        BookingPolicy.OPEN,
    )
    luxe = await get_or_create_venue(
        session, summary, admin,
        "Luxe Cinemas", "Chennai",
        "Phoenix MarketCity, Velachery Main Road, Chennai 600042",
        BookingPolicy.REQUEST,
    )

    audi1 = await get_or_create_screen(session, summary, pvr, LARGE_12x18)
    audi2 = await get_or_create_screen(session, summary, pvr, LARGE_10x14)
    audi3 = await get_or_create_screen(session, summary, pvr, SMALL_8x12)
    luxe1 = await get_or_create_screen(session, summary, luxe, LUXE_10x14)
    luxe2 = await get_or_create_screen(session, summary, luxe, LUXE_8x12)

    # --- events -----------------------------------------------------------
    events = {
        spec.slug: await get_or_create_event(session, summary, organiser, spec)
        for spec in EVENTS
    }

    # --- future shows -----------------------------------------------------
    #
    # Slots are placed per screen with a gap comfortably wider than the
    # longest runtime plus the configured buffer, so no two shows on a screen
    # can overlap however the events are assigned.
    #: Daytime slots only. The three demo-target shows below are placed in the
    #: evening on named screens, so keeping the rotation before 18:00 means a
    #: rotated show can never overlap one of them -- the longest runtime here
    #: is 152 minutes and the configured buffer is 30, so a 14:00 start is
    #: clear by 16:32 and an 18:30 target is safe.
    slots = [(10, 0), (12, 30), (14, 0)]
    open_screens = [audi1, audi2, audi3]
    request_screens = [luxe1, luxe2]

    movie_slugs = ["nebula-drift", "quantum-hour", "kaaval-nagaram", "long-monsoon"]
    live_slugs = ["under-review", "carnatic-electric"]

    shows: list[Show] = []
    combo_index = 0
    plan: list[tuple[Screen, datetime, str, str, ShowFormat | None]] = []

    for day_offset in range(7):
        day = today + timedelta(days=day_offset)
        for screen_index, screen in enumerate(open_screens):
            # One show per screen per day across the week: 3 screens x 7 days
            # is 21, plus the three demo targets -- roughly twenty upcoming
            # shows, spread over screens and times.
            for slot_index in range(1):
                hour, minute = slots[(screen_index + day_offset) % len(slots)]
                # Live events land on the small screen in the evening; movies
                # everywhere else.
                if screen is audi3 and slot_index == 0 and day_offset % 3 == 0:
                    slug = live_slugs[day_offset % len(live_slugs)]
                    language, show_format = "English", None
                else:
                    slug = movie_slugs[(day_offset + screen_index + slot_index)
                                       % len(movie_slugs)]
                    language, show_format = LANGUAGE_FORMATS[
                        combo_index % len(LANGUAGE_FORMATS)
                    ]
                    combo_index += 1
                plan.append((screen, at(day, hour, minute), slug, language,
                             show_format))

    # Guarantee coverage: every advertised language/format pair gets at least
    # one show, whatever the rotation above happened to produce.
    covered = {(lang, fmt) for _s, _t, _e, lang, fmt in plan}
    filler_day = today + timedelta(days=6)
    filler_hour = 9
    for language, show_format in LANGUAGE_FORMATS:
        if (language, show_format) in covered:
            continue
        plan.append(
            (luxe1, at(filler_day, filler_hour), movie_slugs[0], language, show_format)
        )
        filler_hour += 4
        if filler_hour > 21:
            filler_day += timedelta(days=1)
            filler_hour = 9

    for screen, starts_at, slug, language, show_format in plan:
        prices = LUXE_PRICING if screen in request_screens else PRICING
        shows.append(
            await get_or_create_show(
                session, summary, organiser, events[slug], screen,
                starts_at, language, show_format, prices,
            )
        )

    # --- demo target 1: a show TODAY in the evening -----------------------
    tonight = await get_or_create_show(
        session, summary, organiser, events["nebula-drift"], audi1,
        at(today, 19, 30), "English", ShowFormat.IMAX, PRICING,
    )
    summary.targets["tonight's show (booking demo)"] = (
        f"show_id={tonight.id}  Nebula Drift  {LARGE_12x18.name}  "
        f"{at(today, 19, 30).astimezone(IST):%d %b %H:%M} IST"
    )

    # --- demo target 2: one seat from sold out ----------------------------
    #
    # The VIP category on Audi 2 is the smallest in the building, so filling
    # it leaves a genuinely sold-out category to waitlist against without
    # writing hundreds of rows.
    near = await get_or_create_show(
        session, summary, organiser, events["quantum-hour"], audi2,
        at(today + timedelta(days=2), 20, 0), "English", ShowFormat.TWO_D, PRICING,
    )
    vip = (await categories_of(session, audi2.id))["VIP"]
    vip_seats = await seats_in_category(session, audi2.id, vip.id)
    to_fill = vip_seats[:-1]  # every VIP seat but the last
    for index in range(0, len(to_fill), 5):
        chunk = to_fill[index : index + 5]
        await make_booking(
            session, summary, crowd[(index // 5) % len(crowd)], near, chunk,
            vip, PRICING["VIP"], datetime.now(timezone.utc) - timedelta(hours=6),
        )
    remaining = vip_seats[-1]
    summary.targets["near-sold-out (waitlist demo)"] = (
        f"show_id={near.id}  category_id={vip.id} (VIP)  "
        f"{len(vip_seats) - 1}/{len(vip_seats)} sold, "
        f"seat {remaining.row_label}{remaining.seat_number} left"
    )

    # --- demo target 3: a comfortably cancellable booking -----------------
    far = await get_or_create_show(
        session, summary, organiser, events["long-monsoon"], audi1,
        at(today + timedelta(days=6), 18, 30), "Tamil", ShowFormat.TWO_D, PRICING,
    )
    premium_far = (await categories_of(session, audi1.id))["Premium"]
    far_seats = await seats_in_category(session, audi1.id, premium_far.id)
    cancellable = await make_booking(
        session, summary, regular, far, far_seats[:2], premium_far,
        PRICING["Premium"], datetime.now(timezone.utc) - timedelta(hours=2),
    )
    if cancellable is not None:
        summary.targets["cancellable booking"] = (
            f"reference={cancellable.reference}  show_id={far.id}  "
            f"owner=regular@essemble.dev  starts in 6 days"
        )
    else:
        existing = await session.scalar(
            select(Booking)
            .where(Booking.show_id == far.id, Booking.user_id == regular.id)
            .order_by(Booking.created_at.desc())
        )
        if existing is not None:
            summary.targets["cancellable booking"] = (
                f"reference={existing.reference}  show_id={far.id}  "
                f"owner=regular@essemble.dev  starts in 6 days"
            )

    # --- history for regular@essemble.dev ---------------------------------
    #
    # Four months of real bookings on real past shows: 4 sci-fi, 2 action,
    # 3 stand-up, Premium, two seats, 7-10 PM. The recommendation logic reads
    # booking -> booking_seat -> show -> event, so every link has to exist.
    history_plan = [
        ("nebula-drift", 118, 19, 30),
        ("quantum-hour", 104, 20, 0),
        ("nebula-drift", 89, 21, 0),
        ("quantum-hour", 72, 19, 0),
        ("kaaval-nagaram", 61, 22, 0),
        ("kaaval-nagaram", 47, 20, 30),
        ("under-review", 33, 20, 0),
        ("under-review", 20, 21, 30),
        ("under-review", 9, 19, 30),
    ]
    history_screens = [audi1, audi2, audi3]
    for index, (slug, days_ago, hour, minute) in enumerate(history_plan):
        screen = history_screens[index % len(history_screens)]
        past_day = today - timedelta(days=days_ago)
        past_show = await get_or_create_show(
            session, summary, organiser, events[slug], screen,
            at(past_day, hour, minute),
            "English" if slug != "kaaval-nagaram" else "Tamil",
            None if events[slug].event_type is EventType.LIVE else ShowFormat.TWO_D,
            PRICING,
        )
        premium = (await categories_of(session, screen.id))["Premium"]
        pool = await seats_in_category(session, screen.id, premium.id)
        # Walk the pool so repeat visits to one screen take different seats.
        offset = (index * 2) % max(len(pool) - 2, 1)
        await make_booking(
            session, summary, regular, past_show, pool[offset : offset + 2],
            premium, PRICING["Premium"],
            datetime.now(timezone.utc) - timedelta(days=days_ago + 1),
        )

    # --- a pending venue request ------------------------------------------
    pending = await session.scalar(
        select(VenueRequest).where(
            VenueRequest.organiser_id == organiser.id,
            VenueRequest.venue_id == luxe.id,
            VenueRequest.state == VenueRequestState.PENDING,
        )
    )
    if pending is None:
        luxe_categories = await categories_of(session, luxe1.id)
        pending = VenueRequest(
            organiser_id=organiser.id,
            venue_id=luxe.id,
            screen_id=luxe1.id,
            event_id=events["carnatic-electric"].id,
            starts_at=at(today + timedelta(days=10), 19, 0),
            ends_at=at(today + timedelta(days=12), 22, 0),
            shows_per_day=1,
            language="Tamil",
            format=None,
            expected_audience=120,
            proposed_pricing={
                str(category.id): str(LUXE_PRICING[name])
                for name, category in luxe_categories.items()
            },
            state=VenueRequestState.PENDING,
        )
        session.add(pending)
        await session.flush()
        summary.note("venue_requests", True)
    else:
        summary.note("venue_requests", False)
    summary.targets["pending venue request"] = (
        f"request_id={pending.id}  Luxe Cinemas / {LUXE_10x14.name}  "
        f"awaiting admin@essemble.dev"
    )

    # --- a waiting waitlist entry -----------------------------------------
    waiting = await session.scalar(
        select(WaitlistEntry).where(
            WaitlistEntry.show_id == near.id,
            WaitlistEntry.user_id == newcomer.id,
            WaitlistEntry.state == WaitlistEntryState.WAITING,
        )
    )
    if waiting is None:
        waiting = WaitlistEntry(
            show_id=near.id,
            category_id=vip.id,
            user_id=newcomer.id,
            qty=2,
            state=WaitlistEntryState.WAITING,
        )
        session.add(waiting)
        await session.flush()
        summary.note("waitlist_entries", True)
    else:
        summary.note("waitlist_entries", False)
    summary.targets["waiting waitlist entry"] = (
        f"entry_id={waiting.id}  new@essemble.dev, qty 2, VIP on show {near.id}"
    )

    await session.commit()
    return summary


# ------------------------------------------------------------------ output


TABLES_TO_COUNT = [
    "user_account", "venue", "screen", "seat_category", "seat",
    "event", "show", "show_category_price", "seat_claim", "booking",
    "booking_seat", "waitlist_entry", "waitlist_offer", "venue_request",
    "outbox",
]


async def print_summary(session: AsyncSession, summary: Summary) -> None:
    width = 74
    print()
    print("=" * width)
    print("ESSEMBLE seed complete".center(width))
    print("=" * width)

    print("\nROW COUNTS")
    for table in TABLES_TO_COUNT:
        count = await session.scalar(text(f"SELECT count(*) FROM {table}"))
        print(f"  {table:<22} {count:>7}")

    print("\nTHIS RUN")
    for kind in sorted(set(summary.created) | set(summary.reused)):
        made = summary.created.get(kind, 0)
        kept = summary.reused.get(kind, 0)
        print(f"  {kind:<22} {made:>7} created   {kept:>5} already present")

    print("\nCREDENTIALS   (password for every account: essemble123)")
    for email, role in (
        ("admin@essemble.dev", "admin -- owns both venues, approves requests"),
        ("organiser@essemble.dev", "organiser -- owns every event and show"),
        ("new@essemble.dev", "customer -- no history, on the waitlist"),
        ("regular@essemble.dev", "customer -- 4 months of bookings"),
    ):
        print(f"  {email:<26} {role}")
    print("  crowd1..6@essemble.dev     customer -- filler, fills the sold-out show")

    print("\nDEMO TARGETS")
    for label, value in summary.targets.items():
        print(f"  {label}")
        print(f"      {value}")
    print()
    print("=" * width)


# -------------------------------------------------------------------- cli


def reset_is_allowed(force: bool) -> tuple[bool, str]:
    """Whether --reset may proceed against the configured DSN."""
    host = (urlsplit(settings.database_url).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return True, f"host {host!r} is local"
    if force:
        return True, f"host {host!r} is remote, overridden explicitly"
    return False, host


async def do_reset(session: AsyncSession) -> None:
    await session.execute(
        text(f"TRUNCATE {APPLICATION_TABLES} RESTART IDENTITY CASCADE")
    )
    await session.commit()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the ESSEMBLE demo world. Idempotent; safe to re-run."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE every application table before seeding.",
    )
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        dest="force",
        help="Permit --reset against a non-local database host.",
    )
    args = parser.parse_args()

    print(f"database host: {settings.db_host}")

    if args.reset:
        allowed, reason = reset_is_allowed(args.force)
        if not allowed:
            print(
                f"\nREFUSING --reset against host {reason!r}.\n"
                "\n"
                "This is not a local database, and --reset truncates every\n"
                "application table. A hosted demo database is not recoverable\n"
                "from this script.\n"
                "\n"
                "If you are certain, re-run with:\n"
                "    --reset --i-know-what-im-doing\n",
                file=sys.stderr,
            )
            return 2
        print(f"--reset permitted: {reason}")
        async with SessionFactory() as session:
            await do_reset(session)
        print("application tables truncated")

    async with SessionFactory() as session:
        summary = await seed(session)
        await print_summary(session, summary)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
