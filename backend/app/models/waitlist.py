"""Waitlist entries and the time-limited offers they turn into.

A waitlist entry is a standing request for `qty` seats in one category of one
show. When a booking is cancelled the freed seats are matched against the
oldest fitting entry and an offer is created -- and, in the same transaction,
the seats are re-claimed with holder_type='waitlist_offer' so that nobody
browsing the seat map can take them (I6).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, pk_column
from app.models.enums import WaitlistEntryState, WaitlistOfferState


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entry"

    id: Mapped[int] = pk_column()
    show_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("show.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seat_category.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[WaitlistEntryState] = mapped_column(
        pg_enum(WaitlistEntryState, "waitlist_entry_state"),
        nullable=False,
        server_default=text("'waiting'"),
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        Index("ix_waitlist_entry_user_id", "user_id"),
        # Queue-order lookup and the one-active-entry-per-user rule are both
        # partial indexes, declared by hand in the migration.
    )


class WaitlistOffer(Base):
    __tablename__ = "waitlist_offer"

    id: Mapped[int] = pk_column()
    entry_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("waitlist_entry.id", ondelete="CASCADE"), nullable=False
    )
    # Seats reserved for this offer. They also carry live seat_claim rows with
    # holder_type='waitlist_offer' and holder_id = this offer.
    seat_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    # sha256 of the raw token. The raw token is emailed and never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[WaitlistOfferState] = mapped_column(
        pg_enum(WaitlistOfferState, "waitlist_offer_state"),
        nullable=False,
        server_default=text("'pending'"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint(
            "cardinality(seat_ids) > 0", name="seat_ids_not_empty"
        ),
        Index("ix_waitlist_offer_entry_id", "entry_id"),
    )
