"""venue_request

Slot requests against a venue whose booking_policy is 'request'. Added as its
own revision rather than folded into 0001 so that an already-migrated database
moves forward instead of being rebuilt.

Revision ID: 0002_venue_request
Revises: 0001_initial
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_venue_request"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES: tuple[str, ...] = ("pending", "approved", "rejected")


def upgrade() -> None:
    rendered = ", ".join(f"'{value}'" for value in STATES)
    op.execute(f"CREATE TYPE venue_request_state AS ENUM ({rendered})")

    op.create_table(
        "venue_request",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("organiser_id", sa.BigInteger(), nullable=False),
        sa.Column("venue_id", sa.BigInteger(), nullable=False),
        sa.Column("screen_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "shows_per_day", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("expected_audience", sa.Integer(), nullable=True),
        # {"<category_id>": "<decimal string>"} for every seat_category on the
        # target screen. Held here because approval, not submission, is what
        # creates the show -- an unapproved show must not exist in `show`.
        sa.Column(
            "proposed_pricing",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(*STATES, name="venue_request_state", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("admin_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organiser_id"],
            ["user_account.id"],
            name="fk_venue_request_organiser_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["venue.id"],
            name="fk_venue_request_venue_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["screen_id"],
            ["screen.id"],
            name="fk_venue_request_screen_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name="fk_venue_request_event_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="window_ordered"),
        sa.CheckConstraint("shows_per_day > 0", name="shows_per_day_positive"),
        sa.CheckConstraint(
            "expected_audience IS NULL OR expected_audience > 0",
            name="expected_audience_positive",
        ),
        sa.CheckConstraint(
            "state = 'pending' OR decided_at IS NOT NULL", name="decided_has_timestamp"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_pricing) = 'object'"
            " AND proposed_pricing <> '{}'::jsonb",
            name="proposed_pricing_non_empty_object",
        ),
    )
    op.create_index(
        "ix_venue_request_organiser_id_created_at",
        "venue_request",
        ["organiser_id", "created_at"],
    )
    op.create_index("ix_venue_request_event_id", "venue_request", ["event_id"])

    # Admin queue: pending requests for one venue, oldest first.
    op.execute(
        """
        CREATE INDEX ix_venue_request_pending_queue
            ON venue_request (venue_id, created_at)
            WHERE state = 'pending'
        """
    )


def downgrade() -> None:
    op.drop_table("venue_request")
    op.execute("DROP TYPE IF EXISTS venue_request_state")
