"""Server-sent seat-map events.

This endpoint needs a long-lived process and will not work on serverless. The
versioned `GET /api/shows/{id}/seatmap?since=` poll path is the fallback and
remains fully supported -- SSE is an upgrade on it, never a replacement.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import not_found
from app.models import Show
from app.workers.listener import broker

logger = logging.getLogger("essemble.stream")

router = APIRouter(prefix="/api", tags=["booking"])

HEARTBEAT_SECONDS = 20


async def _events(show_id: int) -> AsyncIterator[str]:
    """Yield until the client goes away.

    Disconnection arrives as the generator being closed, which runs the
    finally block below. There is deliberately no `request.is_disconnected()`
    poll: it consumes from the receive channel and can block indefinitely.
    """
    queue = broker.subscribe(show_id)
    try:
        # Tell the client what it is attached to, so a stream that connects
        # but never fires is distinguishable from one that failed to attach.
        yield f": connected show={show_id}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                # Proxies drop a silent connection; a comment keeps it warm
                # without looking like an event to the client.
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
    finally:
        # Always, on disconnect or on error, or the broker leaks a queue per
        # connection for the lifetime of the process.
        broker.unsubscribe(show_id, queue)


@router.get(
    "/shows/{show_id}/seatmap/stream",
    summary="Live seat-map events (SSE)",
    response_class=StreamingResponse,
)
async def seatmap_stream(
    show_id: int,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream seat-status changes for one show.

    Each event is the same information the `?since` poll returns in aggregate:
    `{show_id, seat_ids, status, seat_version}`.

    Errors:
      * `NOT_FOUND` (404) -- no such show.
    """
    exists = await session.scalar(select(Show.id).where(Show.id == show_id))
    if exists is None:
        raise not_found("No such show.")

    return StreamingResponse(
        _events(show_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx buffers streamed responses by default, which would hold
            # events until the buffer fills.
            "X-Accel-Buffering": "no",
        },
    )


@contextlib.asynccontextmanager
async def subscription(show_id: int):
    """In-process subscription, for tests and for any server-side consumer."""
    queue = broker.subscribe(show_id)
    try:
        yield queue
    finally:
        broker.unsubscribe(show_id, queue)
