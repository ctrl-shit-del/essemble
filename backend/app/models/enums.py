"""Domain enumerations.

Each of these is materialised as a native PostgreSQL enum type. The `name`
given to sa.Enum() in the models must match the type name created in the
migration.
"""

from enum import Enum


class UserRole(str, Enum):
    CUSTOMER = "customer"
    ORGANISER = "organiser"
    ADMIN = "admin"


class BookingPolicy(str, Enum):
    OPEN = "open"
    REQUEST = "request"


class VenueRequestState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EventType(str, Enum):
    MOVIE = "movie"
    LIVE = "live"


class ShowFormat(str, Enum):
    TWO_D = "2D"
    THREE_D = "3D"
    IMAX = "IMAX"
    EPIQ_3D = "EPIQ_3D"


class ShowStatus(str, Enum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ClaimState(str, Enum):
    HELD = "held"
    BOOKED = "booked"
    EXPIRED = "expired"
    RELEASED = "released"


class HolderType(str, Enum):
    USER = "user"
    WAITLIST_OFFER = "waitlist_offer"


class BookingStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class WaitlistEntryState(str, Enum):
    WAITING = "waiting"
    OFFERED = "offered"
    CONVERTED = "converted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class WaitlistOfferState(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    EXPIRED = "expired"


class OutboxState(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


#: Claim states that occupy a seat. The partial unique index
#: `one_active_claim` is defined over exactly this set -- it is the sole
#: mechanism guaranteeing that two concurrent requests cannot both take a seat.
ACTIVE_CLAIM_STATES = (ClaimState.HELD, ClaimState.BOOKED)
