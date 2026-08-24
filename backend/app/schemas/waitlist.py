"""Waitlist, offer, cancellation and booking-history models."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import BookingStatus, WaitlistEntryState
from app.schemas.booking import BookingShowSummary, HeldSeat
from app.schemas.common import Money


class WaitlistJoin(BaseModel):
    show_id: int
    category_id: int
    qty: int = Field(ge=1)


class WaitlistEntryResponse(BaseModel):
    id: int
    show: BookingShowSummary
    category_id: int
    category_name: str
    qty: int
    state: WaitlistEntryState
    #: Computed on read from created_at ordering. Never stored, so an upstream
    #: cancellation cannot force everyone behind it to be renumbered.
    position: int | None
    created_at: datetime
    #: Present only while state='offered'. The token itself is never returned;
    #: it exists solely in the email.
    offer_expires_at: datetime | None = None
    offer_seconds_remaining: int | None = None


class CancelledOffer(BaseModel):
    offer_id: int
    entry_id: int
    seat_ids: list[int]
    seat_labels: list[str]
    category_name: str
    expires_at: datetime


class CancelResponse(BaseModel):
    reference: str
    status: str
    cancelled_at: datetime | None
    refund_amount: Money
    #: Offers handed out from the seats this cancellation freed. The seats
    #: behind these are held, not available.
    offers_created: list[CancelledOffer]


class OfferPreview(BaseModel):
    """What the token alone buys you: a read-only view of the offer."""

    show: BookingShowSummary
    category_name: str
    seats: list[HeldSeat]
    total: Money
    expires_at: datetime
    seconds_remaining: int


class BookingListItem(BaseModel):
    reference: str
    status: BookingStatus
    show: BookingShowSummary
    seats: list[HeldSeat]
    total: Money
    qr_signature: str | None
    checked_in_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime


class WaitlistLeaveResponse(BaseModel):
    """Result of leaving the waitlist: the entry and its resulting state."""

    id: int
    state: WaitlistEntryState
