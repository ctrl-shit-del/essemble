"""End-to-end concurrency proof.

Runs against a LIVE server over HTTP. Nothing here is called in-process: the
whole point is that the guarantee survives the real stack -- uvicorn, the
connection pool, the transaction boundaries and PostgreSQL -- not just the
service layer under a test harness.

    python scripts/concurrency_test.py --base-url http://localhost:8000

Four scenarios, each firing N requests that leave at the same instant through
an asyncio barrier. A loop that fires them one after another proves nothing,
so every scenario reports the wall-clock spread of its departure times: if
that spread is not small, the requests did not actually overlap and the run
should not be believed.

HTTP proves what a client sees. The database is then queried directly to
prove what was actually written -- a 409 to 49 clients means little if the
seat ended up with two live claims anyway.

The script provisions its own organiser, customers and shows under a random
run id, so it never competes with seeded demo data and can be run repeatedly.
It does consume seats on the shows it creates, which is why it creates them.

Exit code is 0 only if every assertion in every scenario passed.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import asyncpg
import httpx

# Run either as `python scripts/concurrency_test.py` or `python -m
# scripts.concurrency_test`. The first form does not put the backend root on
# sys.path, and the DSN default is read from the app's own settings.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PASSWORD = "essemble123"

#: Scenario sizes. Kept as constants so the printed report can quote them.
N_HOLD_RACERS = 50
N_CONFIRM_RACERS = 20
N_OVERLAP_RACERS_PER_GROUP = 20
N_CLAIM_RACERS = 10


# ------------------------------------------------------------- barrier shim


class _FallbackBarrier:
    """asyncio.Barrier arrived in 3.11; this project also runs on 3.10.

    Same contract for the single use here: every waiter blocks until the last
    one arrives, then they all proceed together.
    """

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._count = 0
        self._event = asyncio.Event()

    async def wait(self) -> None:
        self._count += 1
        if self._count >= self._parties:
            self._event.set()
        else:
            await self._event.wait()


Barrier = getattr(asyncio, "Barrier", _FallbackBarrier)


# ----------------------------------------------------------------- results


@dataclass
class Check:
    label: str
    expected: object
    actual: object

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


@dataclass
class Scenario:
    number: int
    title: str
    detail: str
    checks: list[Check] = field(default_factory=list)
    departures: list[float] = field(default_factory=list)
    arrivals: list[float] = field(default_factory=list)
    note: str | None = None

    def check(self, label: str, expected: object, actual: object) -> None:
        self.checks.append(Check(label, expected, actual))

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def spread_ms(self) -> float | None:
        if len(self.departures) < 2:
            return None
        return (max(self.departures) - min(self.departures)) * 1000

    @property
    def stdev_ms(self) -> float | None:
        if len(self.departures) < 2:
            return None
        return statistics.pstdev(self.departures) * 1000

    @property
    def all_in_flight(self) -> bool:
        """True when every request was open at one instant.

        The last request left before the first reply came back, so at the
        moment of that last departure all N were in flight at once. This is
        the claim that matters -- a small departure spread alone would not
        rule out the first request having already completed.
        """
        if not self.departures or not self.arrivals:
            return False
        return max(self.departures) < min(self.arrivals)

    @property
    def overlap_ms(self) -> float | None:
        """Margin by which the last departure beat the first reply."""
        if not self.departures or not self.arrivals:
            return None
        return (min(self.arrivals) - max(self.departures)) * 1000

    def assert_overlapped(self) -> None:
        self.check("all requests in flight simultaneously", True, self.all_in_flight)


# ---------------------------------------------------------------- plumbing


def asyncpg_dsn(database_url: str) -> tuple[str, str | None]:
    """(dsn, ssl) for asyncpg, from a SQLAlchemy-flavoured URL."""
    parts = urlsplit(database_url.replace("+asyncpg", ""))
    query = dict(parse_qsl(parts.query))
    ssl_value = query.pop("ssl", None) or query.pop("sslmode", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), ssl_value


class Api:
    """Thin HTTP client. Every call in this script goes through here."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def register(self, email: str, name: str, role: str) -> str:
        r = await self.client.post(
            "/api/auth/register",
            json={"email": email, "password": PASSWORD, "name": name, "role": role},
        )
        if r.status_code == 201:
            return r.json()["access_token"]
        # Already present from a previous run with the same id: log in instead.
        r = await self.client.post(
            "/api/auth/login", json={"email": email, "password": PASSWORD}
        )
        r.raise_for_status()
        return r.json()["access_token"]

    async def seatmap(self, show_id: int) -> dict:
        r = await self.client.get(f"/api/shows/{show_id}/seatmap")
        r.raise_for_status()
        return r.json()


async def gather_bounded(coros, limit: int = 10):
    """Run setup work concurrently but politely."""
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))


# ------------------------------------------------------------------- setup


@dataclass
class World:
    api: Api
    db: asyncpg.Connection
    run_id: str
    organiser: str
    customers: list[str]
    screen_id: int
    pricing: dict[int, str]


async def pick_open_screen(db: asyncpg.Connection) -> int:
    """A screen at a venue whose booking_policy is 'open'.

    A 'request' venue would answer show creation with 202 and a pending
    approval instead of a show, which is correct behaviour and useless here.
    """
    row = await db.fetchrow(
        """
        SELECT s.id
          FROM screen s
          JOIN venue v ON v.id = s.venue_id
         WHERE v.booking_policy = 'open'
           AND EXISTS (SELECT 1 FROM seat WHERE seat.screen_id = s.id)
         ORDER BY s.total_seats DESC
         LIMIT 1
        """
    )
    if row is None:
        raise SystemExit(
            "No screen with seats at an 'open' venue.\n"
            "Run `python -m scripts.seed` first."
        )
    return row["id"]


async def screen_pricing(db: asyncpg.Connection, screen_id: int) -> dict[int, str]:
    rows = await db.fetch(
        "SELECT id, rank FROM seat_category WHERE screen_id = $1 ORDER BY rank",
        screen_id,
    )
    # Any consistent price will do; nothing here is asserted on money.
    return {row["id"]: f"{200 + 100 * row['rank']}.00" for row in rows}


async def create_show(world: World, day_offset: int, title_suffix: str) -> int:
    """A fresh show, far enough out that no seeded show can overlap it."""
    r = await world.api.client.post(
        "/api/organiser/events",
        headers=Api.auth(world.organiser),
        json={
            "event_type": "movie",
            "title": f"Concurrency Probe {world.run_id} {title_suffix}",
            "runtime_min": 90,
            "genres": ["Test"],
            "certification": "U",
        },
    )
    r.raise_for_status()
    event_id = r.json()["id"]

    # Retry forward on 409: the screen may already be busy at that instant,
    # which is the scheduler working, not a failure.
    starts_at = datetime.now(timezone.utc) + timedelta(days=45 + day_offset)
    starts_at = starts_at.replace(hour=6, minute=0, second=0, microsecond=0)
    for _ in range(24):
        r = await world.api.client.post(
            "/api/organiser/shows",
            headers=Api.auth(world.organiser),
            json={
                "event_id": event_id,
                "screen_id": world.screen_id,
                "starts_at": starts_at.isoformat(),
                "language": "English",
                "format": "2D",
                "pricing": world.pricing,
            },
        )
        if r.status_code == 201:
            return r.json()["show"]["id"]
        if r.status_code != 409:
            r.raise_for_status()
        starts_at += timedelta(hours=4)
    raise SystemExit("could not find a free slot on the target screen")


async def build_world(api: Api, db: asyncpg.Connection) -> World:
    run_id = uuid.uuid4().hex[:8]
    print(f"  run id            {run_id}")

    organiser = await api.register(
        f"probe-org-{run_id}@essemble.dev", "Probe Organiser", "organiser"
    )
    customers = await gather_bounded(
        [
            api.register(
                f"probe-{run_id}-{i:03d}@essemble.dev", f"Probe {i}", "customer"
            )
            for i in range(N_HOLD_RACERS)
        ]
    )
    print(f"  accounts          1 organiser + {len(customers)} customers")

    screen_id = await pick_open_screen(db)
    pricing = await screen_pricing(db, screen_id)
    print(f"  target screen     screen_id={screen_id}")

    return World(
        api=api,
        db=db,
        run_id=run_id,
        organiser=organiser,
        customers=list(customers),
        screen_id=screen_id,
        pricing=pricing,
    )


# --------------------------------------------------------------- the races


async def fire(barrier, scenario: "Scenario", request) -> httpx.Response | Exception:
    """Wait at the barrier, stamp the departure, go, stamp the arrival."""
    await barrier.wait()
    scenario.departures.append(time.perf_counter())
    try:
        return await request()
    except Exception as exc:  # noqa: BLE001 -- a transport error is a result
        return exc
    finally:
        scenario.arrivals.append(time.perf_counter())


def tally(responses: list) -> dict[int, int]:
    counts: dict[int, int] = {}
    for r in responses:
        code = r.status_code if isinstance(r, httpx.Response) else 0
        counts[code] = counts.get(code, 0) + 1
    return counts


def error_codes(responses: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in responses:
        if not isinstance(r, httpx.Response) or r.status_code < 400:
            continue
        try:
            code = r.json()["error"]["code"]
        except Exception:  # noqa: BLE001
            code = f"<unparseable {r.status_code}>"
        counts[code] = counts.get(code, 0) + 1
    return counts


async def scenario_1_single_seat(world: World) -> Scenario:
    scenario = Scenario(
        1,
        "Simultaneous holds on one seat",
        f"{N_HOLD_RACERS} distinct users, one seat, released together",
    )
    show_id = await create_show(world, 0, "S1")
    seatmap = await world.api.seatmap(show_id)
    seat_id = next(s["seat_id"] for s in seatmap["seats"] if s["status"] == "available")

    barrier = Barrier(N_HOLD_RACERS)

    def request_for(token: str):
        async def go():
            return await world.api.client.post(
                "/api/holds",
                headers=Api.auth(token),
                json={"show_id": show_id, "seat_ids": [seat_id]},
            )

        return go

    responses = await asyncio.gather(
        *(
            fire(barrier, scenario, request_for(token))
            for token in world.customers[:N_HOLD_RACERS]
        )
    )

    counts = tally(responses)
    codes = error_codes(responses)
    scenario.check("HTTP 201 (hold granted)", 1, counts.get(201, 0))
    scenario.check("HTTP 409 (seat taken)", N_HOLD_RACERS - 1, counts.get(409, 0))
    scenario.check(
        "error code SEAT_UNAVAILABLE",
        N_HOLD_RACERS - 1,
        codes.get("SEAT_UNAVAILABLE", 0),
    )

    scenario.assert_overlapped()

    active = await world.db.fetchval(
        """
        SELECT count(*) FROM seat_claim
         WHERE show_id = $1 AND seat_id = $2 AND state IN ('held','booked')
        """,
        show_id,
        seat_id,
    )
    scenario.check("DB: active claims on that seat", 1, active)
    scenario.note = f"show_id={show_id}, seat_id={seat_id}"
    return scenario


async def scenario_2_confirm_race(world: World) -> Scenario:
    scenario = Scenario(
        2,
        "Simultaneous confirms of one hold",
        f"{N_CONFIRM_RACERS} concurrent confirms of a single hold group",
    )
    show_id = await create_show(world, 1, "S2")
    seatmap = await world.api.seatmap(show_id)
    seat_ids = [
        s["seat_id"] for s in seatmap["seats"] if s["status"] == "available"
    ][:2]

    owner = world.customers[0]
    r = await world.api.client.post(
        "/api/holds",
        headers=Api.auth(owner),
        json={"show_id": show_id, "seat_ids": seat_ids},
    )
    r.raise_for_status()
    group = r.json()["hold_group_id"]

    barrier = Barrier(N_CONFIRM_RACERS)

    def go():
        return world.api.client.post(
            f"/api/holds/{group}/confirm", headers=Api.auth(owner)
        )

    responses = await asyncio.gather(
        *(
            fire(barrier, scenario, go)
            for _ in range(N_CONFIRM_RACERS)
        )
    )

    counts = tally(responses)
    created = counts.get(201, 0)
    others = sum(n for code, n in counts.items() if code != 201)
    scenario.check("HTTP 201 (booking created)", 1, created)
    scenario.check(
        "replayed or rejected", N_CONFIRM_RACERS - 1, others
    )
    scenario.check(
        "every non-201 is a 4xx",
        True,
        all(400 <= c < 500 for c in counts if c != 201),
    )

    scenario.assert_overlapped()

    bookings = await world.db.fetchval(
        "SELECT count(*) FROM booking WHERE hold_group_id = $1", uuid.UUID(group)
    )
    scenario.check("DB: bookings for that hold group", 1, bookings)

    booked = await world.db.fetchval(
        """
        SELECT count(*) FROM seat_claim
         WHERE hold_group_id = $1 AND state = 'booked'
        """,
        uuid.UUID(group),
    )
    scenario.check("DB: booked claims", len(seat_ids), booked)
    scenario.note = (
        f"show_id={show_id}, group={group}, "
        + ", ".join(f"{n}x{code}" for code, n in sorted(counts.items()))
    )
    return scenario


async def scenario_3_overlapping_multi_seat(world: World) -> Scenario:
    scenario = Scenario(
        3,
        "Overlapping multi-seat holds",
        f"{N_OVERLAP_RACERS_PER_GROUP} clients want (A,B,C), "
        f"{N_OVERLAP_RACERS_PER_GROUP} want (C,D,E)",
    )
    show_id = await create_show(world, 2, "S3")
    seatmap = await world.api.seatmap(show_id)
    free = [s["seat_id"] for s in seatmap["seats"] if s["status"] == "available"][:5]
    group_a, group_b = free[0:3], free[2:5]
    contested = free[2]

    total = N_OVERLAP_RACERS_PER_GROUP * 2
    barrier = Barrier(total)

    def request_for(token: str, seats: list[int]):
        async def go():
            return await world.api.client.post(
                "/api/holds",
                headers=Api.auth(token),
                json={"show_id": show_id, "seat_ids": seats},
            )

        return go

    # Distinct user per request: one live hold group per user per show is a
    # rule of the engine, and reusing a user would test that rule instead of
    # the seat race.
    tokens = world.customers[:total]
    requests = [
        request_for(token, group_a if index % 2 == 0 else group_b)
        for index, token in enumerate(tokens)
    ]
    responses = await asyncio.gather(
        *(fire(barrier, scenario, req) for req in requests)
    )

    counts = tally(responses)
    codes = error_codes(responses)

    # Only one request can win: both sets contain the contested seat, so a
    # winner of either set locks every other request out of it.
    scenario.check("HTTP 201 (holds granted)", 1, counts.get(201, 0))
    scenario.check("HTTP 409 (lost the race)", total - 1, counts.get(409, 0))
    scenario.check(
        "error code SEAT_UNAVAILABLE", total - 1, codes.get("SEAT_UNAVAILABLE", 0)
    )

    scenario.assert_overlapped()

    rows = await world.db.fetch(
        """
        SELECT seat_id, hold_group_id FROM seat_claim
         WHERE show_id = $1 AND state IN ('held','booked')
        """,
        show_id,
    )
    held_seats = {row["seat_id"] for row in rows}
    groups = {row["hold_group_id"] for row in rows}

    scenario.check("DB: distinct hold groups alive", 1, len(groups))
    scenario.check("DB: seats held", 3, len(held_seats))
    scenario.check(
        "DB: the contested seat is held exactly once",
        1,
        sum(1 for row in rows if row["seat_id"] == contested),
    )
    # All-or-nothing: the winning set is intact and nothing else survived, so
    # no loser left a partial hold behind.
    scenario.check(
        "DB: winning set is whole and exclusive",
        True,
        held_seats in (set(group_a), set(group_b)),
    )
    scenario.note = (
        f"show_id={show_id}, A={group_a}, B={group_b}, contested={contested}"
    )
    return scenario


async def sell_out_category(
    world: World, show_id: int, seat_ids: list[int]
) -> list[str]:
    """Book every seat given, in chunks, and return the booking references."""
    references = []
    chunk_size = 10  # MAX_SEATS_PER_HOLD
    chunks = [
        seat_ids[i : i + chunk_size] for i in range(0, len(seat_ids), chunk_size)
    ]
    for index, chunk in enumerate(chunks):
        token = world.customers[index % len(world.customers)]
        r = await world.api.client.post(
            "/api/holds",
            headers=Api.auth(token),
            json={"show_id": show_id, "seat_ids": chunk},
        )
        r.raise_for_status()
        group = r.json()["hold_group_id"]
        r = await world.api.client.post(
            f"/api/holds/{group}/confirm", headers=Api.auth(token)
        )
        r.raise_for_status()
        references.append((r.json()["reference"], token))
    return references


async def scenario_4_offer_claim_race(world: World) -> Scenario:
    scenario = Scenario(
        4,
        "Simultaneous claims of one offer",
        f"{N_CLAIM_RACERS} concurrent claims with the same single-use token",
    )
    show_id = await create_show(world, 3, "S4")

    # Smallest category on the screen: selling it out is the setup cost, and
    # nothing about the race depends on how big it is.
    smallest = await world.db.fetchrow(
        """
        SELECT c.id AS id, count(s.id) AS n
          FROM seat_category c JOIN seat s ON s.category_id = c.id
         WHERE c.screen_id = $1
         GROUP BY c.id ORDER BY n ASC LIMIT 1
        """,
        world.screen_id,
    )
    category_id = smallest["id"]

    seat_rows = await world.db.fetch(
        "SELECT id FROM seat WHERE category_id = $1 ORDER BY y, x", category_id
    )
    seat_ids = [row["id"] for row in seat_rows]
    references = await sell_out_category(world, show_id, seat_ids)

    # A waitlister, then a cancellation to produce the offer.
    waiter = world.customers[-1]
    r = await world.api.client.post(
        "/api/waitlist",
        headers=Api.auth(waiter),
        json={"show_id": show_id, "category_id": category_id, "qty": 2},
    )
    r.raise_for_status()

    reference, owner_token = references[0]
    r = await world.api.client.post(
        f"/api/bookings/{reference}/cancel", headers=Api.auth(owner_token)
    )
    r.raise_for_status()
    offers = r.json()["offers_created"]
    if not offers:
        scenario.check("an offer was created by the cancellation", True, False)
        return scenario
    offer_id = offers[0]["offer_id"]

    # The raw token exists only in the email the outbox is holding; only its
    # hash is stored on the offer. Reading it here is exactly what the
    # recipient would do with the link.
    claim_url = await world.db.fetchval(
        """
        SELECT payload->>'claim_url' FROM outbox
         WHERE template = 'waitlist_offer'
         ORDER BY created_at DESC LIMIT 1
        """
    )
    token = claim_url.rsplit("/", 1)[1]

    barrier = Barrier(N_CLAIM_RACERS)

    def go():
        return world.api.client.post(
            f"/api/waitlist/offers/{token}/claim", headers=Api.auth(waiter)
        )

    responses = await asyncio.gather(
        *(fire(barrier, scenario, go) for _ in range(N_CLAIM_RACERS))
    )

    counts = tally(responses)
    codes = error_codes(responses)
    scenario.check("HTTP 201 (offer claimed)", 1, counts.get(201, 0))
    scenario.check("HTTP 410 (already used)", N_CLAIM_RACERS - 1, counts.get(410, 0))
    scenario.check(
        "error code OFFER_EXPIRED", N_CLAIM_RACERS - 1, codes.get("OFFER_EXPIRED", 0)
    )

    scenario.assert_overlapped()

    # One booking, however many claims were fired. Counted over DISTINCT
    # bookings rather than rows, since the join fans out one row per seat.
    bookings = await world.db.fetchval(
        """
        SELECT count(DISTINCT b.id) FROM booking b
          JOIN seat_claim c ON c.hold_group_id = b.hold_group_id
         WHERE b.show_id = $1 AND c.holder_id = $2
           AND c.holder_type = 'waitlist_offer'
        """,
        show_id,
        offer_id,
    )
    scenario.check("DB: bookings from that offer", 1, bookings)

    state = await world.db.fetchval(
        "SELECT state::text FROM waitlist_offer WHERE id = $1", offer_id
    )
    scenario.check("DB: offer state", "claimed", state)
    scenario.note = f"show_id={show_id}, offer_id={offer_id}"
    return scenario


# ------------------------------------------------------------------ report


WIDTH = 78


def render(scenarios: list[Scenario]) -> bool:
    print()
    print("=" * WIDTH)
    print("ESSEMBLE CONCURRENCY PROOF".center(WIDTH))
    print("=" * WIDTH)

    all_passed = True
    for scenario in scenarios:
        all_passed = all_passed and scenario.passed
        print()
        print(f"SCENARIO {scenario.number}  {scenario.title}")
        print(f"  {scenario.detail}")
        if scenario.note:
            print(f"  {scenario.note}")
        spread = scenario.spread_ms
        if spread is not None:
            print(
                f"  departure spread  {spread:.1f} ms across "
                f"{len(scenario.departures)} requests "
                f"(sd {scenario.stdev_ms:.1f} ms)"
            )
            margin = scenario.overlap_ms
            if margin is not None:
                print(
                    f"  overlap           last request left "
                    f"{margin:.1f} ms before the first reply arrived"
                )
        print("  " + "-" * (WIDTH - 4))
        print(f"  {'CHECK':<44}{'EXPECTED':>12}{'ACTUAL':>12}   ")
        for check in scenario.checks:
            mark = "ok " if check.ok else "FAIL"
            print(
                f"  {check.label:<44}{str(check.expected):>12}"
                f"{str(check.actual):>12}  {mark}"
            )
        print("  " + "-" * (WIDTH - 4))
        print(f"  {'PASS' if scenario.passed else 'FAIL'}")

    print()
    print("=" * WIDTH)
    total = sum(len(s.checks) for s in scenarios)
    failed = sum(1 for s in scenarios for c in s.checks if not c.ok)
    verdict = "PASS" if all_passed else "FAIL"
    print(
        f"{verdict}   {len(scenarios)} scenarios, {total} assertions, "
        f"{failed} failed".center(WIDTH)
    )
    print("=" * WIDTH)
    return all_passed


# --------------------------------------------------------------------- cli


async def run(base_url: str, database_url: str) -> int:
    print("ESSEMBLE concurrency proof")
    print(f"  target            {base_url}")

    dsn, ssl_value = asyncpg_dsn(database_url)
    limits = httpx.Limits(max_connections=256, max_keepalive_connections=128)

    async with httpx.AsyncClient(
        base_url=base_url, timeout=120, limits=limits
    ) as client:
        try:
            health = await client.get("/api/health")
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"\nCannot reach {base_url}: {exc}", file=sys.stderr)
            print("Start the server first, e.g. `uvicorn app.main:app`.",
                  file=sys.stderr)
            return 2
        body = health.json()
        print(f"  server            {body['status']}, db {body['database']}, "
              f"migration {body['migration_revision']}")

        db = await asyncpg.connect(dsn, ssl=ssl_value)
        try:
            api = Api(client)
            world = await build_world(api, db)

            scenarios = [
                await scenario_1_single_seat(world),
                await scenario_2_confirm_race(world),
                await scenario_3_overlapping_multi_seat(world),
                await scenario_4_offer_claim_race(world),
            ]
        finally:
            await db.close()

    return 0 if render(scenarios) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove the booking engine's concurrency guarantees over HTTP."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of a running ESSEMBLE server.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="DSN for the direct assertions. Defaults to the app's own setting.",
    )
    args = parser.parse_args()

    database_url = args.database_url
    if database_url is None:
        from app.core.config import settings

        database_url = settings.database_url

    return asyncio.run(run(args.base_url, database_url))


if __name__ == "__main__":
    raise SystemExit(main())
