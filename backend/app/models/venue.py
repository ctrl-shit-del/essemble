"""Venue topology: venue -> screen -> seat_category / seat."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, pk_column
from app.models.enums import BookingPolicy


class Venue(Base):
    __tablename__ = "venue"

    id: Mapped[int] = pk_column()
    admin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    booking_policy: Mapped[BookingPolicy] = mapped_column(
        pg_enum(BookingPolicy, "booking_policy"),
        nullable=False,
        server_default=text("'open'"),
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_venue_admin_id", "admin_id"),)


class Screen(Base):
    __tablename__ = "screen"

    id: Mapped[int] = pk_column()
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venue.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    total_seats: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("venue_id", "name", name="uq_screen_venue_id_name"),
        CheckConstraint("total_seats >= 0", name="total_seats_non_negative"),
    )


class SeatCategory(Base):
    __tablename__ = "seat_category"

    id: Mapped[int] = pk_column()
    screen_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("screen.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("screen_id", "name", name="uq_seat_category_screen_id_name"),
        CheckConstraint("rank > 0", name="rank_positive"),
    )


class Seat(Base):
    __tablename__ = "seat"

    id: Mapped[int] = pk_column()
    screen_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("screen.id", ondelete="CASCADE"), nullable=False
    )
    row_label: Mapped[str] = mapped_column(String(4), nullable=False)
    seat_number: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seat_category.id", ondelete="RESTRICT"), nullable=False
    )
    # Layout coordinates. x already accounts for aisle offsets so the client
    # can render an irregular hall without inferring geometry.
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        UniqueConstraint(
            "screen_id",
            "row_label",
            "seat_number",
            name="uq_seat_screen_id_row_label_seat_number",
        ),
        Index("ix_seat_screen_id", "screen_id"),
        Index("ix_seat_category_id", "category_id"),
        CheckConstraint("seat_number > 0", name="seat_number_positive"),
    )
