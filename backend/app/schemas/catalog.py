"""Event and show models."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EventType, ShowFormat, ShowStatus
from app.schemas.common import Money
from app.schemas.venue import SeatCategoryResponse


class EventCreate(BaseModel):
    event_type: EventType
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    runtime_min: int | None = Field(default=None, ge=1, le=1000)
    certification: str | None = Field(default=None, max_length=16)
    genres: list[str] = Field(default_factory=list)
    release_date: date | None = None
    tmdb_id: int | None = None
    artist_name: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _by_type(self) -> "EventCreate":
        # A movie without a runtime cannot be scheduled: the overlap check
        # needs it to know when the screen frees up.
        if self.event_type is EventType.MOVIE and self.runtime_min is None:
            raise ValueError("runtime_min is required for a movie")
        if self.event_type is EventType.LIVE and not self.artist_name:
            raise ValueError("artist_name is required for a live event")
        return self


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organiser_id: int
    event_type: EventType
    title: str
    description: str | None
    poster_url: str | None
    backdrop_url: str | None
    runtime_min: int | None
    certification: str | None
    genres: list[str]
    release_date: date | None
    tmdb_id: int | None
    artist_name: str | None
    created_at: datetime


class EventListItem(EventResponse):
    """Catalog listing row, with the honest show-derived numbers attached."""

    upcoming_shows: int
    next_show_at: datetime | None
    cities: list[str]
    from_price: Money | None


class ShowCreate(BaseModel):
    event_id: int
    screen_id: int
    starts_at: datetime
    language: str = Field(min_length=1, max_length=40)
    format: ShowFormat | None = None
    #: category_id -> price. Every seat_category on the target screen must be
    #: present; anything else is rejected.
    pricing: dict[int, Money] = Field(min_length=1)


class ShowUpdate(BaseModel):
    starts_at: datetime | None = None
    language: str | None = Field(default=None, min_length=1, max_length=40)
    format: ShowFormat | None = None
    status: ShowStatus | None = None
    pricing: dict[int, Money] | None = None


class CategoryPrice(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int
    name: str
    rank: int
    price: Money


class ShowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    screen_id: int
    organiser_id: int
    starts_at: datetime
    language: str
    format: ShowFormat | None
    status: ShowStatus
    seat_version: int
    created_at: datetime


class ShowDetail(ShowResponse):
    event: EventResponse
    venue_id: int
    venue_name: str
    city: str
    screen_name: str
    total_seats: int
    pricing: list[CategoryPrice]


class ShowtimeItem(BaseModel):
    """One screening, grouped under its venue by the caller."""

    show_id: int
    starts_at: datetime
    language: str
    format: ShowFormat | None
    venue_id: int
    venue_name: str
    city: str
    screen_id: int
    screen_name: str
    from_price: Money | None


class VenueShowtimes(BaseModel):
    venue_id: int
    venue_name: str
    city: str
    address: str
    shows: list[ShowtimeItem]


class ScreenCategories(BaseModel):
    screen_id: int
    categories: list[SeatCategoryResponse]


Section = Literal["popular", "now_showing", "upcoming", "live"]
