"""Venue, screen and layout logic.

Ownership rule for this whole module: `require_role(ADMIN)` establishes that
the caller is *an* admin. It never establishes that a given venue is *theirs*.
Every function here that takes an id re-derives ownership from the database.
"""

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import conflict, forbidden
from app.models import (
    Screen,
    Seat,
    SeatCategory,
    SeatClaim,
    Show,
    UserAccount,
    Venue,
)
from app.schemas.venue import (
    LayoutRequest,
    LayoutResponse,
    ScreenCreate,
    ScreenResponse,
    SeatCategoryResponse,
    SeatResponse,
    VenueCreate,
    VenueResponse,
)
from app.venues.layout import generate_seats


async def load_owned_venue(
    session: AsyncSession, venue_id: int, admin: UserAccount
) -> Venue:
    """The venue, or 403.

    Missing and not-yours answer identically on purpose: a 404 for unknown ids
    and a 403 for someone else's would turn the id space into an oracle for
    enumerating which venues exist.
    """
    venue = await session.scalar(select(Venue).where(Venue.id == venue_id))
    if venue is None or venue.admin_id != admin.id:
        raise forbidden("That venue does not belong to you.")
    return venue


async def load_owned_screen(
    session: AsyncSession, screen_id: int, admin: UserAccount
) -> tuple[Screen, Venue]:
    """The screen and its venue, or 403. Walks screen -> venue -> admin_id."""
    row = (
        await session.execute(
            select(Screen, Venue)
            .join(Venue, Venue.id == Screen.venue_id)
            .where(Screen.id == screen_id)
        )
    ).first()
    if row is None or row[1].admin_id != admin.id:
        raise forbidden("That screen does not belong to you.")
    return row[0], row[1]


async def list_venues(
    session: AsyncSession, admin: UserAccount
) -> list[VenueResponse]:
    venues = (
        await session.scalars(
            select(Venue).where(Venue.admin_id == admin.id).order_by(Venue.created_at)
        )
    ).all()
    return [VenueResponse.model_validate(v) for v in venues]


async def create_venue(
    session: AsyncSession, admin: UserAccount, payload: VenueCreate
) -> VenueResponse:
    venue = Venue(admin_id=admin.id, **payload.model_dump())
    session.add(venue)
    await session.commit()
    await session.refresh(venue)
    return VenueResponse.model_validate(venue)


async def create_screen(
    session: AsyncSession, admin: UserAccount, venue_id: int, payload: ScreenCreate
) -> ScreenResponse:
    venue = await load_owned_venue(session, venue_id, admin)

    duplicate = await session.scalar(
        select(Screen.id).where(
            Screen.venue_id == venue.id, Screen.name == payload.name
        )
    )
    if duplicate is not None:
        raise conflict(f"{venue.name} already has a screen named {payload.name!r}.")

    screen = Screen(venue_id=venue.id, name=payload.name, total_seats=0)
    session.add(screen)
    await session.commit()
    await session.refresh(screen)
    return ScreenResponse.model_validate(screen)


async def generate_layout(
    session: AsyncSession, admin: UserAccount, screen_id: int, payload: LayoutRequest
) -> LayoutResponse:
    """Create categories and seats for a screen.

    Regeneration is refused once ANY seat_claim exists for ANY show on the
    screen -- held, booked, expired or released. Replacing the seat rows would
    orphan booking_seat and leave claims pointing at seats that no longer
    describe the same physical place.
    """
    screen, _venue = await load_owned_screen(session, screen_id, admin)

    has_claims = await session.scalar(
        select(
            exists().where(
                SeatClaim.show_id == Show.id,
                Show.screen_id == screen.id,
            )
        )
    )
    if has_claims:
        raise conflict(
            "This screen already has seat claims; regenerating the layout would "
            "orphan existing bookings.",
            {"screen_id": screen.id},
        )

    # Geometry first: a validation failure must not leave a half-wiped screen.
    generated = generate_seats(
        payload.rows,
        payload.seats_per_row,
        payload.aisle_after_columns,
        payload.categories,
    )

    existing_seats = await session.scalar(
        select(func.count()).select_from(Seat).where(Seat.screen_id == screen.id)
    )
    if existing_seats:
        await session.execute(delete(Seat).where(Seat.screen_id == screen.id))
        await session.execute(
            delete(SeatCategory).where(SeatCategory.screen_id == screen.id)
        )
        await session.flush()

    categories = {
        spec.name: SeatCategory(screen_id=screen.id, name=spec.name, rank=spec.rank)
        for spec in payload.categories
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
    await session.execute(
        update(Screen).where(Screen.id == screen.id).values(total_seats=len(generated))
    )
    await session.commit()

    return await read_layout(session, screen.id, payload)


async def read_layout(
    session: AsyncSession, screen_id: int, payload: LayoutRequest
) -> LayoutResponse:
    categories = (
        await session.scalars(
            select(SeatCategory)
            .where(SeatCategory.screen_id == screen_id)
            .order_by(SeatCategory.rank)
        )
    ).all()
    seats = (
        await session.scalars(
            select(Seat).where(Seat.screen_id == screen_id).order_by(Seat.y, Seat.x)
        )
    ).all()
    return LayoutResponse(
        screen_id=screen_id,
        total_seats=len(seats),
        rows=payload.rows,
        seats_per_row=payload.seats_per_row,
        aisle_after_columns=payload.aisle_after_columns,
        categories=[SeatCategoryResponse.model_validate(c) for c in categories],
        seats=[SeatResponse.model_validate(s) for s in seats],
    )
