"""Venue slot requests and their decisions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ShowFormat, VenueRequestState
from app.schemas.catalog import ShowResponse
from app.schemas.common import Money


class VenueRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organiser_id: int
    venue_id: int
    venue_name: str
    screen_id: int
    screen_name: str
    event_id: int
    event_title: str
    starts_at: datetime
    ends_at: datetime
    shows_per_day: int
    language: str
    format: ShowFormat | None
    expected_audience: int | None
    #: category_id -> price, parsed back out of JSONB into Decimal.
    proposed_pricing: dict[int, Money]
    state: VenueRequestState
    admin_message: str | None
    created_at: datetime
    decided_at: datetime | None


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    admin_message: str | None = Field(default=None, max_length=2000)


class DecisionResponse(BaseModel):
    request: VenueRequestResponse
    #: Present only on approval -- the show materialised from the request.
    show: ShowResponse | None = None


class ShowScheduleResult(BaseModel):
    """Result of POST /api/organiser/shows.

    Two outcomes, one model with an explicit discriminator rather than an
    ambiguous union: an 'open' venue creates the show (201), a 'request' venue
    creates a pending venue_request and no `show` row at all (202).
    """

    status: Literal["created", "pending_approval"]
    show: ShowResponse | None = None
    venue_request: VenueRequestResponse | None = None
