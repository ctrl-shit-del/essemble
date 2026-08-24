"""Organiser requests for slots at a venue whose booking_policy is 'request'.

When `venue.booking_policy = 'request'`, an organiser cannot schedule a show
directly. Show creation returns 202 and lands here instead, for the venue
admin to approve or reject.
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
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, pk_column
from app.models.enums import ShowFormat, VenueRequestState


class VenueRequest(Base):
    __tablename__ = "venue_request"

    id: Mapped[int] = pk_column()
    organiser_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venue.id", ondelete="CASCADE"), nullable=False
    )
    screen_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("screen.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("event.id", ondelete="CASCADE"), nullable=False
    )
    # The window the organiser is asking for, not a single showtime: a request
    # can cover a multi-day run at shows_per_day.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shows_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    # Show fields that must survive the pending period. show.language is NOT
    # NULL, so approval could not materialise a show without them, and asking
    # the organiser to re-enter anything defeats the point of the request path.
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    format: Mapped[ShowFormat | None] = mapped_column(
        pg_enum(ShowFormat, "show_format"), nullable=True
    )
    expected_audience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-category pricing submitted with the request, shaped
    # {"<category_id>": "<decimal string>"} -- one entry per seat_category on
    # the target screen at request time.
    #
    # It lives here because no `show` row exists yet: a request-policy venue
    # answers POST /organiser/shows with 202 and nothing is written to `show`.
    # Unapproved shows must not exist in that table at all, so that no catalog
    # query, showtime lookup or seatmap read can leak one by forgetting a
    # status filter. Approval materialises the show from this column, and the
    # organiser never re-enters anything.
    #
    # Prices are JSON strings, parsed to Decimal in Python. Never float.
    proposed_pricing: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    state: Mapped[VenueRequestState] = mapped_column(
        pg_enum(VenueRequestState, "venue_request_state"),
        nullable=False,
        server_default=text("'pending'"),
    )
    # Free text from the admin on approval or rejection.
    admin_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="window_ordered"),
        CheckConstraint("shows_per_day > 0", name="shows_per_day_positive"),
        CheckConstraint(
            "expected_audience IS NULL OR expected_audience > 0",
            name="expected_audience_positive",
        ),
        CheckConstraint(
            "state = 'pending' OR decided_at IS NOT NULL", name="decided_has_timestamp"
        ),
        CheckConstraint(
            "jsonb_typeof(proposed_pricing) = 'object'"
            " AND proposed_pricing <> '{}'::jsonb",
            name="proposed_pricing_non_empty_object",
        ),
        Index("ix_venue_request_organiser_id_created_at", "organiser_id", "created_at"),
        Index("ix_venue_request_event_id", "event_id"),
        # The admin queue index is partial; declared by hand in the migration.
    )

    # On approval (POST /admin/venue-requests/{id}/decision):
    #  1. Re-run the screen overlap check. Another organiser may have booked
    #     this slot through the normal path while the request sat pending, and
    #     two pending requests for the same slot can both reach approval. This
    #     cannot be a CHECK constraint -- it spans rows. Approval is the only
    #     place the constraint is real; return 409 if the slot is gone.
    #  2. Validate every key in proposed_pricing against the screen's CURRENT
    #     seat_category ids. The admin may have regenerated the layout since
    #     the request was filed. Reject if any category is missing or unknown.
    #  3. Only then create the show and its show_category_price rows.
