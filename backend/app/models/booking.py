"""Seat claims and bookings -- the graded core of the data model.

INVARIANT I1: there is deliberately no `status` column on `seat`. The status
of a seat for a given show is derived from this table at read time:

    booked    -> an active claim with state='booked'
    held      -> an active claim with state='held' AND expires_at > now()
    available -> anything else

INVARIANT I2: mutual exclusion between concurrent bookers is enforced by the
partial unique index `one_active_claim` on (show_id, seat_id) WHERE
state IN ('held','booked') -- not by application-level locking.

INVARIANT I3: expiry is lazy and authoritative. `expires_at` in the past means
the hold is gone whether or not the sweeper has run.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, pk_column
from app.models.enums import BookingStatus, ClaimState, HolderType


class SeatClaim(Base):
    __tablename__ = "seat_claim"

    id: Mapped[int] = pk_column()
    show_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("show.id", ondelete="CASCADE"), nullable=False
    )
    seat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seat.id", ondelete="RESTRICT"), nullable=False
    )
    # Groups the seats acquired by a single multi-seat hold. All-or-nothing:
    # any seat lost rolls the whole group back (I5).
    hold_group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[ClaimState] = mapped_column(
        pg_enum(ClaimState, "claim_state"), nullable=False
    )
    holder_type: Mapped[HolderType] = mapped_column(
        pg_enum(HolderType, "holder_type"), nullable=False
    )
    # Polymorphic, keyed by holder_type: user_account.id, or waitlist_offer.id
    # when the seat is locked behind a time-limited waitlist offer (I6).
    # Deliberately carries no foreign key because it addresses two tables.
    holder_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # NULL once booked -- a confirmed booking never expires.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint(
            "state <> 'held' OR expires_at IS NOT NULL",
            name="held_claim_has_expiry",
        ),
        CheckConstraint(
            "state <> 'booked' OR expires_at IS NULL",
            name="booked_claim_has_no_expiry",
        ),
        Index("ix_seat_claim_hold_group_id", "hold_group_id"),
        Index("ix_seat_claim_seat_id", "seat_id"),
        # The one_active_claim unique index and the other partial indexes on
        # this table are written by hand in the migration.
    )


class Booking(Base):
    __tablename__ = "booking"

    id: Mapped[int] = pk_column()
    reference: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    show_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("show.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    hold_group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        pg_enum(BookingStatus, "booking_status"),
        nullable=False,
        server_default=text("'confirmed'"),
    )
    qr_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint(
            "reference ~ '^ESB-[A-Z0-9]{6}$'", name="reference_format"
        ),
        Index("ix_booking_user_id_created_at", "user_id", "created_at"),
        Index("ix_booking_show_id", "show_id"),
        Index("ix_booking_hold_group_id", "hold_group_id"),
    )


class BookingSeat(Base):
    __tablename__ = "booking_seat"

    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("booking.id", ondelete="CASCADE"), primary_key=True
    )
    seat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seat.id", ondelete="RESTRICT"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seat_category.id", ondelete="RESTRICT"), nullable=False
    )
    # Price frozen at confirmation time. Re-pricing a show must never rewrite
    # what an existing customer paid.
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    __table_args__ = (CheckConstraint("price >= 0", name="price_non_negative"),)
