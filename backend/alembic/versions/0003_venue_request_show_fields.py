"""venue_request: carry the show fields needed to materialise on approval

proposed_pricing alone is not enough to create a show. `show.language` is NOT
NULL and `show.format` is part of what the organiser submitted, so both have to
survive the pending period -- otherwise approval would have to ask the
organiser to re-enter them, which is exactly what the request path exists to
avoid.

0002 is already applied, so this is a new revision rather than an amendment.

Revision ID: 0003_vr_show_fields
Revises: 0002_venue_request
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_vr_show_fields"
down_revision: str | None = "0002_venue_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHOW_FORMATS = ("2D", "3D", "IMAX", "EPIQ_3D")


def upgrade() -> None:
    # Added with a default so the NOT NULL is safe on a populated table, then
    # the default is dropped: language is always supplied explicitly.
    op.add_column(
        "venue_request",
        sa.Column(
            "language",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'English'"),
        ),
    )
    op.alter_column("venue_request", "language", server_default=None)

    op.add_column(
        "venue_request",
        sa.Column(
            "format",
            postgresql.ENUM(*SHOW_FORMATS, name="show_format", create_type=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("venue_request", "format")
    op.drop_column("venue_request", "language")
