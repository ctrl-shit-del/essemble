"""Postgres LISTEN/NOTIFY fan-out.

REQUIRES A LONG-LIVED PROCESS. LISTEN holds a session open, so this cannot
work on serverless, and it will silently receive nothing behind a
transaction-mode pooler (which is why a pooled DSN is refused at startup).
The versioned `?since` poll path on the seat map exists precisely for those
deployments and is never removed -- SSE is an upgrade, not the mechanism.

The connection is a RAW asyncpg connection, deliberately not taken from the
SQLAlchemy pool: a pooled connection would be recycled out from under the
LISTEN and the stream would go quiet with no error.
"""

import asyncio
import contextlib
import json
import logging
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import asyncpg

from app.booking.events import CHANNEL
from app.core.config import settings

logger = logging.getLogger("essemble.listener")

#: Bounded per-subscriber queue. A client that cannot keep up is dropped
#: rather than allowed to grow the process's memory without limit; it falls
#: back to polling.
QUEUE_SIZE = 100
KEEPALIVE_SECONDS = 30
RECONNECT_MAX_SECONDS = 30


def _asyncpg_dsn() -> tuple[str, str | None]:
    """(dsn, ssl) for asyncpg, from the SQLAlchemy URL."""
    parts = urlsplit(settings.database_url.replace("+asyncpg", ""))
    query = dict(parse_qsl(parts.query))
    ssl_value = query.pop("ssl", None) or query.pop("sslmode", None)
    dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return dsn, ssl_value


class SeatChangeBroker:
    """Fans one LISTEN connection out to per-show subscriber queues."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = {}
        self._task: asyncio.Task | None = None
        self._connection: asyncpg.Connection | None = None
        self.connected = False

    # ------------------------------------------------------------ subscribe

    def subscribe(self, show_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.setdefault(show_id, set()).add(queue)
        return queue

    def unsubscribe(self, show_id: int, queue: asyncio.Queue) -> None:
        queues = self._subscribers.get(show_id)
        if not queues:
            return
        queues.discard(queue)
        if not queues:
            # Drop the empty set too, so the dict cannot grow one key per show
            # ever streamed.
            self._subscribers.pop(show_id, None)

    def subscriber_count(self, show_id: int) -> int:
        return len(self._subscribers.get(show_id, ()))

    # -------------------------------------------------------------- fan-out

    def dispatch(self, raw: str) -> None:
        try:
            event = json.loads(raw)
            show_id = int(event["show_id"])
        except (ValueError, KeyError, TypeError):
            logger.warning("ignoring malformed seat_changes payload")
            return

        for queue in list(self._subscribers.get(show_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("subscriber for show %s fell behind; dropping", show_id)
                self.unsubscribe(show_id, queue)

    # ----------------------------------------------------------- connection

    async def _listen_forever(self) -> None:
        dsn, ssl_value = _asyncpg_dsn()
        delay = 1.0
        while True:
            try:
                self._connection = await asyncpg.connect(dsn, ssl=ssl_value)
                await self._connection.add_listener(
                    CHANNEL, lambda _c, _p, _ch, payload: self.dispatch(payload)
                )
                self.connected = True
                delay = 1.0
                logger.info("listening on %s", CHANNEL)

                # Keepalive: a managed provider will drop an idle connection,
                # and a dead LISTEN produces no error of its own -- the stream
                # just goes quiet.
                while True:
                    await asyncio.sleep(KEEPALIVE_SECONDS)
                    await self._connection.execute("SELECT 1")

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- reconnect on anything
                self.connected = False
                logger.warning("listener connection lost (%s); retrying in %.0fs",
                               exc, delay)
                await self._close_connection()
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    async def _close_connection(self) -> None:
        if self._connection is not None:
            with contextlib.suppress(Exception):
                await self._connection.close()
            self._connection = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen_forever())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._close_connection()
        self.connected = False
        self._subscribers.clear()


broker = SeatChangeBroker()
