"""Infrastructure tables: the email outbox and the idempotency ledger."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, pk_column
from app.models.enums import OutboxState


class Outbox(Base):
    """Transactional outbox for email (I7).

    A request never talks to the mail provider. It inserts a row here inside
    the same transaction as the booking, and a worker delivers it afterwards.
    A provider outage therefore cannot roll back or block a confirmed booking.
    """

    __tablename__ = "outbox"

    id: Mapped[int] = pk_column()
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    state: Mapped[OutboxState] = mapped_column(
        pg_enum(OutboxState, "outbox_state"),
        nullable=False,
        server_default=text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (CheckConstraint("attempts >= 0", name="attempts_non_negative"),)


class IdempotencyKey(Base):
    """Replay ledger for unsafe POSTs.

    The stored response is written inside the same transaction as the effect
    it describes, so a client retry can never produce a second hold.
    """

    __tablename__ = "idempotency_key"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    #: sha256 of the normalised request body, so a retry can be distinguished
    #: from the same key reused for a different request.
    request_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
