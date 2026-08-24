"""APScheduler wiring for the two background workers.

Started and stopped by the FastAPI lifespan. `coalesce` and
`max_instances=1` matter on a free tier: after the instance wakes from sleep,
APScheduler would otherwise try to make up every missed run at once.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.workers import outbox, sweeper

logger = logging.getLogger("essemble.workers")

_scheduler: AsyncIOScheduler | None = None


def start() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.workers_enabled:
        logger.info("workers disabled by configuration")
        return None

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        sweeper.run_tick,
        "interval",
        seconds=settings.sweeper_interval_seconds,
        id="sweeper",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    if settings.outbox_enabled:
        _scheduler.add_job(
            outbox.run_tick,
            "interval",
            seconds=settings.outbox_interval_seconds,
            id="outbox",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
    _scheduler.start()
    logger.info(
        "workers started: sweeper every %ss, outbox every %ss (driver=%s)",
        settings.sweeper_interval_seconds,
        settings.outbox_interval_seconds,
        settings.mail_driver,
    )
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
