"""Catalog: events, shows and per-show pricing."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, pk_column
from app.models.enums import EventType, ShowFormat, ShowStatus


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = pk_column()
    organiser_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(
        pg_enum(EventType, "event_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    certification: Mapped[str | None] = mapped_column(String(16), nullable=True)
    genres: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artist_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint(
            "runtime_min IS NULL OR runtime_min > 0", name="runtime_positive"
        ),
        Index("ix_event_organiser_id", "organiser_id"),
        Index("ix_event_event_type", "event_type"),
    )


class Show(Base):
    __tablename__ = "show"

    id: Mapped[int] = pk_column()
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("event.id", ondelete="CASCADE"), nullable=False
    )
    screen_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("screen.id", ondelete="RESTRICT"), nullable=False
    )
    organiser_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    format: Mapped[ShowFormat | None] = mapped_column(
        pg_enum(ShowFormat, "show_format"), nullable=True
    )
    status: Mapped[ShowStatus] = mapped_column(
        pg_enum(ShowStatus, "show_status"),
        nullable=False,
        server_default=text("'scheduled'"),
    )
    # Monotonic counter bumped by every mutation of the claims belonging to
    # this show. Clients poll ?since=<seat_version> and get 304 when nothing
    # has moved; the SSE stream carries the same number.
    seat_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_show_event_id_starts_at", "event_id", "starts_at"),
        Index("ix_show_screen_id_starts_at", "screen_id", "starts_at"),
        Index("ix_show_organiser_id", "organiser_id"),
    )


class ShowCategoryPrice(Base):
    __tablename__ = "show_category_price"

    show_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("show.id", ondelete="CASCADE"),
        primary_key=True,
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seat_category.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    __table_args__ = (CheckConstraint("price >= 0", name="price_non_negative"),)
