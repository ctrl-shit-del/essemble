"""ESSEMBLE API entrypoint."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app.booking.checkin_router import router as checkin_router
from app.booking.router import router as booking_router
from app.booking.stream_router import router as stream_router
from app.booking.waitlist_router import bookings_router
from app.booking.waitlist_router import router as waitlist_router
from app.catalog.router import organiser_router as catalog_organiser_router
from app.catalog.router import public_router as catalog_public_router
from app.core.config import settings
from app.core.db import SessionFactory, engine
from app.core.errors import register_error_handlers
from app.workers import outbox as outbox_worker
from app.workers import scheduler, sweeper
from app.workers.listener import broker
from app.identity.router import router as auth_router
from app.venues.requests_router import admin_router as requests_admin_router
from app.venues.requests_router import organiser_router as requests_organiser_router
from app.venues.router import router as venues_router

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s"
)
logger = logging.getLogger("essemble")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Print the resolved host on every boot. A pooled DSN is already refused in
    # config, but pooling fails silently -- SSE would connect and deliver
    # nothing -- so the host it actually resolved to is worth stating out loud
    # rather than inferring from a config file.
    if settings.db_is_pooled:
        # Not an assert: -O would strip it.
        raise RuntimeError(
            f"refusing to start against a pooled endpoint ({settings.db_host})"
        )
    logger.info("database host=%s (direct, not pooled)", settings.db_host)
    scheduler.start()
    if settings.realtime_enabled:
        await broker.start()
    yield
    await broker.stop()
    scheduler.shutdown()
    await engine.dispose()


app = FastAPI(
    title="ESSEMBLE API",
    description="Ticket booking for movies and live events.",
    version="0.1.0",
    lifespan=lifespan,
)

# Before any router is registered, so every route below is covered.
#
# The origins are named rather than wildcarded because allow_credentials=True
# rules a wildcard out: a browser refuses `Access-Control-Allow-Origin: *` on
# a credentialed request, so "*" here would not loosen CORS, it would break
# it. Set CORS_ORIGINS to the deployed frontend's URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

for _router in (
    auth_router,
    venues_router,
    requests_admin_router,
    requests_organiser_router,
    catalog_organiser_router,
    catalog_public_router,
    booking_router,
    waitlist_router,
    bookings_router,
    checkin_router,
    stream_router,
):
    app.include_router(_router)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    database: Literal["up", "down"]


class WorkerHealth(BaseModel):
    """Liveness of one in-process background worker.

    `last_run_at` is None until the worker has completed a tick in THIS
    process, which is the honest answer -- it is what proves the scheduler is
    running here, not merely that it is enabled in configuration.
    """

    enabled: bool
    interval_seconds: int
    last_run_at: datetime | None


class HealthDetail(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    database: Literal["up", "down"]
    #: Alembic revision the connected database is actually at. A deployment
    #: running against an un-migrated database is otherwise invisible until a
    #: query fails on a missing column.
    migration_revision: str | None
    sweeper: WorkerHealth
    outbox: WorkerHealth
    #: Rows still waiting to be delivered. A number that only grows means the
    #: dispatcher is wedged even though its last_run_at keeps advancing.
    pending_outbox: int | None
    #: Whether the LISTEN connection behind the SSE stream is up. False with
    #: realtime enabled means clients are silently falling back to polling.
    realtime_connected: bool


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Liveness plus a database round-trip.

    Returns 200 either way; `database` reports reachability so a free-tier
    host waking from sleep is visible rather than silently failing later.

    This route is deliberately cheap and dependency-free, for an uptime
    probe. `GET /api/health` is the detailed version.
    """
    database: Literal["up", "down"] = "down"
    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        database = "up"
    except Exception:  # noqa: BLE001 -- health must never raise
        database = "down"

    return HealthResponse(
        status="ok" if database == "up" else "degraded",
        environment=settings.environment,
        database=database,
    )


@app.get("/api/health", response_model=HealthDetail, tags=["system"])
async def health_detail() -> HealthDetail:
    """Everything needed to tell a live deployment from a merely running one.

    Returns 200 even when degraded: a monitoring endpoint that fails to
    answer tells you nothing about WHY. Read `status` and the fields below.
    """
    database: Literal["up", "down"] = "down"
    revision: str | None = None
    pending: int | None = None
    try:
        async with SessionFactory() as session:
            revision = await session.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            pending = await session.scalar(
                text("SELECT count(*) FROM outbox WHERE state = 'pending'")
            )
        database = "up"
    except Exception:  # noqa: BLE001 -- health must never raise
        database = "down"

    return HealthDetail(
        status="ok" if database == "up" else "degraded",
        environment=settings.environment,
        database=database,
        migration_revision=revision,
        sweeper=WorkerHealth(
            enabled=settings.workers_enabled,
            interval_seconds=settings.sweeper_interval_seconds,
            last_run_at=sweeper.last_run_at,
        ),
        outbox=WorkerHealth(
            enabled=settings.workers_enabled and settings.outbox_enabled,
            interval_seconds=settings.outbox_interval_seconds,
            last_run_at=outbox_worker.last_run_at,
        ),
        pending_outbox=pending,
        realtime_connected=broker.connected,
    )
