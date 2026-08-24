"""idempotency_key: fingerprint the request body

Replaying a stored response is only safe when the retry is the SAME request.
Without a fingerprint, a client reusing a key with a different body would be
handed the first request's response, which is worse than an error. The
fingerprint lets that case answer 409 CONFLICT instead.

Revision ID: 0004_idem_fingerprint
Revises: 0003_vr_show_fields
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_idem_fingerprint"
down_revision: str | None = "0003_vr_show_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "idempotency_key",
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("idempotency_key", "request_fingerprint")
