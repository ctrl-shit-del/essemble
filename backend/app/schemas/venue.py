"""Venue, screen and seat-layout models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import BookingPolicy


class VenueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    city: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1)
    lat: Decimal | None = Field(default=None, ge=-90, le=90)
    lng: Decimal | None = Field(default=None, ge=-180, le=180)
    booking_policy: BookingPolicy = BookingPolicy.OPEN


class VenueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str
    address: str
    lat: Decimal | None
    lng: Decimal | None
    booking_policy: BookingPolicy
    created_at: datetime


class ScreenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ScreenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venue_id: int
    name: str
    total_seats: int
    created_at: datetime


class LayoutCategory(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rank: int = Field(ge=1)
    row_from: str = Field(min_length=1, max_length=4)
    row_to: str = Field(min_length=1, max_length=4)

    @field_validator("row_from", "row_to")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class LayoutRequest(BaseModel):
    rows: int = Field(ge=1, le=100)
    seats_per_row: int = Field(ge=1, le=100)
    #: 1-based column numbers after which an aisle gap is inserted. These shift
    #: the stored x of every later seat, so the client renders the gap without
    #: having to know the rule.
    aisle_after_columns: list[int] = Field(default_factory=list)
    categories: list[LayoutCategory] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_aisles(self) -> "LayoutRequest":
        for column in self.aisle_after_columns:
            if not 1 <= column < self.seats_per_row:
                raise ValueError(
                    f"aisle_after_columns entry {column} must be between 1 and "
                    f"{self.seats_per_row - 1}"
                )
        if len(set(self.aisle_after_columns)) != len(self.aisle_after_columns):
            raise ValueError("aisle_after_columns contains duplicates")
        ranks = [c.rank for c in self.categories]
        if len(set(ranks)) != len(ranks):
            raise ValueError("category ranks must be unique")
        names = [c.name.lower() for c in self.categories]
        if len(set(names)) != len(names):
            raise ValueError("category names must be unique")
        return self


class SeatCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rank: int


class SeatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    row_label: str
    seat_number: int
    category_id: int
    x: int
    y: int
    is_active: bool


class LayoutResponse(BaseModel):
    screen_id: int
    total_seats: int
    rows: int
    seats_per_row: int
    aisle_after_columns: list[int]
    categories: list[SeatCategoryResponse]
    seats: list[SeatResponse]
