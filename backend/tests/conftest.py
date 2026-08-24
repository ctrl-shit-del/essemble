"""Shared fixtures.

These tests run against the real database named by DATABASE_URL. The booking
engine's correctness is a property of PostgreSQL's partial unique index and its
handling of ON CONFLICT, so testing it against anything else would be testing
something other than the thing being graded.

Two things keep the suite fast against a remote database:

  * One event loop for the whole session (`loop_scope="session"`), so the
    connection pool survives between tests. Without it, pooled asyncpg
    connections belong to a dead loop and the pool has to be disabled --
    which costs a TCP+TLS handshake per statement.

  * The venue, screen, layout, event and show are built once. Each test only
    clears the tables it can dirty. That is two round trips per test instead
    of roughly a hundred and twenty.

Assertions deliberately read committed state through a separate connection
(`active_claims`, `seat_version`, `booking_count`), which is what makes them
trustworthy -- they verify what the database actually holds, not what one
session has pending. That is also why per-test isolation is a reset rather
than a transaction rolled back at the end: an uncommitted transaction is
invisible to those helpers.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.db import engine
from app.core.security import hash_password
from app.main import app

#: Everything a test can dirty. Rebuilt per test; one statement.
MUTABLE_TABLES = (
    "booking_seat, booking, seat_claim, waitlist_offer, waitlist_entry, "
    "outbox, idempotency_key"
)

#: Everything, including the fixture scaffolding. Used once per session.
ALL_TABLES = (
    f"{MUTABLE_TABLES}, show_category_price, show, venue_request, event, "
    "seat, seat_category, screen, venue, user_account"
)

LAYOUT = {
    "rows": 4,
    "seats_per_row": 6,
    "aisle_after_columns": [3],
    "categories": [
        {"name": "Premium", "rank": 1, "row_from": "A", "row_to": "B"},
        {"name": "Standard", "rank": 2, "row_from": "C", "row_to": "D"},
    ],
}


@dataclass
class World:
    client: httpx.AsyncClient
    show_id: int
    screen_id: int
    seat_ids: list[int]
    #: Static for the whole session: the seed is built once, so category ids
    #: and the seats in each category never change. Only *status* is dynamic.
    category_ids: dict[str, int] = field(default_factory=dict)
    seats_by_category: dict[str, list[int]] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)

    def auth(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[who]}"}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded():
    """Build the fixture world once for the whole run."""
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))
        await conn.execute(
            text(
                """INSERT INTO user_account (email, password_hash, name, role)
                   VALUES ('admin@t.dev', :p, 'Admin', 'admin')"""
            ),
            {"p": hash_password("essemble123")},
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=60
    ) as client:
        tokens: dict[str, str] = {}

        r = await client.post(
            "/api/auth/login",
            json={"email": "admin@t.dev", "password": "essemble123"},
        )
        tokens["admin"] = r.json()["access_token"]

        for who, role in (
            ("organiser", "organiser"),
            ("alice", "customer"),
            ("bob", "customer"),
            ("carol", "customer"),
        ):
            r = await client.post(
                "/api/auth/register",
                json={
                    "email": f"{who}@t.dev",
                    "password": "essemble123",
                    "name": who.title(),
                    "role": role,
                },
            )
            tokens[who] = r.json()["access_token"]

        admin = {"Authorization": f"Bearer {tokens['admin']}"}
        r = await client.post(
            "/api/admin/venues",
            headers=admin,
            json={"name": "Test Venue", "city": "Pune", "address": "somewhere"},
        )
        venue_id = r.json()["id"]

        r = await client.post(
            f"/api/admin/venues/{venue_id}/screens",
            headers=admin,
            json={"name": "Audi 1"},
        )
        screen_id = r.json()["id"]

        r = await client.post(
            f"/api/admin/screens/{screen_id}/layout", headers=admin, json=LAYOUT
        )
        categories = {c["name"]: c["id"] for c in r.json()["categories"]}
        seat_ids = [s["id"] for s in r.json()["seats"]]
        by_category: dict[str, list[int]] = {}
        id_to_name = {v: k for k, v in categories.items()}
        for seat in r.json()["seats"]:
            by_category.setdefault(id_to_name[seat["category_id"]], []).append(
                seat["id"]
            )

        organiser = {"Authorization": f"Bearer {tokens['organiser']}"}
        r = await client.post(
            "/api/organiser/events",
            headers=organiser,
            json={
                "event_type": "movie",
                "title": "Test Feature",
                "runtime_min": 100,
            },
        )
        event_id = r.json()["id"]

        starts_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        r = await client.post(
            "/api/organiser/shows",
            headers=organiser,
            json={
                "event_id": event_id,
                "screen_id": screen_id,
                "starts_at": starts_at,
                "language": "English",
                "pricing": {
                    str(categories["Premium"]): "400.00",
                    str(categories["Standard"]): "250.00",
                },
            },
        )
        show_id = r.json()["show"]["id"]

        yield World(
            client=client,
            show_id=show_id,
            screen_id=screen_id,
            seat_ids=seat_ids,
            category_ids=categories,
            seats_by_category=by_category,
            tokens=tokens,
        )

    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def world(seeded: World):
    """Hand back the seeded world with every mutable table cleared.

    Also restores the show itself: one test moves starts_at inside the
    cancellation cutoff, and under a shared seed that would leak into every
    test after it.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {MUTABLE_TABLES} RESTART IDENTITY CASCADE")
        )
        await conn.execute(
            text(
                "UPDATE show SET seat_version = 0, status = 'scheduled',"
                " starts_at = now() + interval '3 days' WHERE id = :i"
            ),
            {"i": seeded.show_id},
        )
    return seeded


async def expire_group(group_id: str) -> None:
    """Age a hold past its TTL without waiting, and without sweeping it."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE seat_claim SET expires_at = now() - interval '1 second'"
                " WHERE hold_group_id = CAST(:g AS uuid) AND state = 'held'"
            ),
            {"g": group_id},
        )


async def active_claims(show_id: int, seat_id: int) -> list[tuple]:
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text(
                    """SELECT id, state, holder_id, expires_at FROM seat_claim
                        WHERE show_id = :s AND seat_id = :t
                          AND state IN ('held','booked')"""
                ),
                {"s": show_id, "t": seat_id},
            )
        ).all()


async def seat_version(show_id: int) -> int:
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT seat_version FROM show WHERE id = :i"), {"i": show_id}
            )
        ).scalar_one()


async def booking_count() -> int:
    async with engine.begin() as conn:
        return (
            await conn.execute(text("SELECT count(*) FROM booking"))
        ).scalar_one()
