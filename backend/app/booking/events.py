"""Seat-map change events.

Bumping `show.seat_version` and emitting `pg_notify` are the same event seen
two ways: the version drives the `?since` poll path, the notification drives
the SSE stream. They must never diverge -- a mutation that bumps the version
without notifying leaves pollers correct and streamers stale.

So they are not two things a caller has to remember to do. `bump_and_notify`
is the ONLY place `BUMP_SEAT_VERSION` is executed, and it always notifies.
`test_every_bump_notifies` asserts no other module executes that statement.

pg_notify is transactional: a rolled-back transaction sends nothing, so a
failed hold cannot announce seats it never took.
"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking.sql import BUMP_SEAT_VERSION

CHANNEL = "seat_changes"

NOTIFY = text("SELECT pg_notify(:channel, :payload)")


async def bump_and_notify(
    session: AsyncSession,
    show_id: int,
    *changes: tuple[list[int], str],
) -> int:
    """Advance the seat version and announce what moved.

    Each change is (seat_ids, status). One version bump covers them all, so a
    cancellation that hands some seats to an offer and frees the rest emits
    two events carrying the same version.
    """
    version = await session.scalar(BUMP_SEAT_VERSION, {"show_id": show_id})

    for seat_ids, status in changes:
        if not seat_ids:
            continue
        payload = json.dumps(
            {
                "show_id": show_id,
                "seat_ids": sorted(int(s) for s in seat_ids),
                "status": status,
                "seat_version": version,
            },
            separators=(",", ":"),
        )
        await session.execute(NOTIFY, {"channel": CHANNEL, "payload": payload})

    return version
