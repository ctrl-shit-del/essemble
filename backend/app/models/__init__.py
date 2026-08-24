"""SQLAlchemy models.

Importing this package registers every table on Base.metadata, which is what
alembic/env.py targets.
"""

from app.models.base import Base
from app.models.booking import Booking, BookingSeat, SeatClaim
from app.models.catalog import Event, Show, ShowCategoryPrice
from app.models.enums import (
    ACTIVE_CLAIM_STATES,
    BookingPolicy,
    BookingStatus,
    ClaimState,
    EventType,
    HolderType,
    OutboxState,
    ShowFormat,
    ShowStatus,
    UserRole,
    VenueRequestState,
    WaitlistEntryState,
    WaitlistOfferState,
)
from app.models.system import IdempotencyKey, Outbox
from app.models.user import UserAccount
from app.models.venue import Screen, Seat, SeatCategory, Venue
from app.models.venue_request import VenueRequest
from app.models.waitlist import WaitlistEntry, WaitlistOffer

__all__ = [
    "ACTIVE_CLAIM_STATES",
    "Base",
    "Booking",
    "BookingPolicy",
    "BookingSeat",
    "BookingStatus",
    "ClaimState",
    "Event",
    "EventType",
    "HolderType",
    "IdempotencyKey",
    "Outbox",
    "OutboxState",
    "Screen",
    "Seat",
    "SeatCategory",
    "SeatClaim",
    "Show",
    "ShowCategoryPrice",
    "ShowFormat",
    "ShowStatus",
    "UserAccount",
    "UserRole",
    "Venue",
    "VenueRequest",
    "VenueRequestState",
    "WaitlistEntry",
    "WaitlistEntryState",
    "WaitlistOffer",
    "WaitlistOfferState",
]
