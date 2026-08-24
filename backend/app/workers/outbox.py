"""Transactional outbox dispatcher.

The only thing in the system that sends mail. A request never talks to the
provider: it inserts an outbox row inside its own transaction, and this worker
delivers it afterwards (I7). A provider outage therefore cannot roll back or
block a confirmed booking -- it can only delay an email.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory
from app.notifications import email

logger = logging.getLogger("essemble.outbox")

BATCH = 20
MAX_ATTEMPTS = 5

#: When run_tick last completed, in this process. See sweeper.last_run_at.
last_run_at: datetime | None = None

#: Exponential backoff without an extra column: after a failure a row becomes
#: eligible again 2^attempts seconds after it was created -- 2s, 4s, 8s, 16s.
#: A row that has never been tried is due immediately; backoff applies between
#: attempts, not before the first one.
DUE_ROWS = text(
    """
    SELECT id, template, to_email, payload, attempts
      FROM outbox
     WHERE state = 'pending'
       AND attempts < :max_attempts
       AND created_at + make_interval(
               secs => CASE WHEN attempts = 0 THEN 0
                            ELSE power(2, attempts)::int END
           ) <= now()
     ORDER BY created_at
     LIMIT :batch
     FOR UPDATE SKIP LOCKED
    """
)

MARK_SENT = text(
    "UPDATE outbox SET state = 'sent', sent_at = now(), last_error = NULL"
    " WHERE id = :id"
)

#: One statement for both outcomes: another attempt, or give up at the cap.
MARK_FAILED_ATTEMPT = text(
    """
    UPDATE outbox
       SET attempts = attempts + 1,
           last_error = :error,
           state = CASE WHEN attempts + 1 >= :max_attempts
                        THEN 'failed'::outbox_state
                        ELSE 'pending'::outbox_state END
     WHERE id = :id
    """
)


async def dispatch_once(session: AsyncSession) -> dict[str, int]:
    """Deliver one batch. Never raises: a bad row must not stop the others."""
    rows = (
        await session.execute(
            DUE_ROWS, {"batch": BATCH, "max_attempts": MAX_ATTEMPTS}
        )
    ).all()

    sent = 0
    failed = 0
    for row in rows:
        try:
            email.deliver(row.template, row.to_email, row.payload or {})
        except Exception as exc:  # noqa: BLE001 -- provider errors are data here
            failed += 1
            logger.warning("outbox %s (%s) failed: %s", row.id, row.template, exc)
            await session.execute(
                MARK_FAILED_ATTEMPT,
                {
                    "id": row.id,
                    "error": str(exc)[:2000],
                    "max_attempts": MAX_ATTEMPTS,
                },
            )
        else:
            sent += 1
            await session.execute(MARK_SENT, {"id": row.id})

    await session.commit()
    if sent or failed:
        logger.info("outbox: %d sent, %d failed", sent, failed)
    return {"sent": sent, "failed": failed}


async def run_tick() -> dict[str, int]:
    global last_run_at
    try:
        async with SessionFactory() as session:
            return await dispatch_once(session)
    except Exception:
        logger.exception("outbox dispatch failed; continuing")
        return {"sent": 0, "failed": 0}
    finally:
        last_run_at = datetime.now(timezone.utc)


def enabled() -> bool:
    return settings.outbox_enabled
