"""Seat map, hold and booking models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ShowFormat
from app.schemas.common import Money

SeatStatus = Literal["available", "held", "booked"]


class SeatMapSeat(BaseModel):
    seat_id: int
    row_label: str
    seat_number: int
    x: int
    y: int
    category_id: int
    #: Derived at read time from seat_claim. Never stored, never cached.
    status: SeatStatus


class SeatMapCategory(BaseModel):
    id: int
    name: str
    rank: int
    price: Money


class SeatMapResponse(BaseModel):
    show_id: int
    seat_version: int
    event_title: str
    venue_name: str
    screen_name: str
    starts_at: datetime
    language: str
    format: ShowFormat | None
    rows: int
    columns: int
    categories: list[SeatMapCategory]
    seats: list[SeatMapSeat]


class HoldCreate(BaseModel):
    show_id: int
    seat_ids: list[int] = Field(min_length=1)


class HeldSeat(BaseModel):
    seat_id: int
    row_label: str
    seat_number: int
    category_id: int
    category_name: str
    price: Money


class HoldResponse(BaseModel):
    hold_group_id: UUID
    show_id: int
    expires_at: datetime
    seconds_remaining: int
    seats: list[HeldSeat]
    total: Money


class BookingShowSummary(BaseModel):
    show_id: int
    event_title: str
    venue_name: str
    screen_name: str
    starts_at: datetime
    language: str
    format: ShowFormat | None


class ConfirmResponse(BaseModel):
    reference: str
    status: str
    show: BookingShowSummary
    seats: list[HeldSeat]
    total: Money
    qr_signature: str
    created_at: datetime


class HoldReleaseResponse(BaseModel):
    """Result of releasing a hold early.

    `already_released` distinguishes "you released it" from "there was
    nothing left to release" without making the second case an error --
    releasing twice is deliberately idempotent.
    """

    hold_group_id: UUID
    released_seat_ids: list[int]
    already_released: bool
