"""SSE fan-out, idempotency and the error envelope."""

import asyncio
import inspect

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.booking import events, service
from app.booking.stream_router import subscription
from app.core.db import SessionFactory, engine
from app.main import app
from app.workers import sweeper
from app.workers.listener import broker

pytestmark = pytest.mark.asyncio(loop_scope="session")

EVENT_TIMEOUT = 10


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def listening():
    """One LISTEN connection for the whole run, as in production."""
    await broker.start()
    for _ in range(100):
        if broker.connected:
            break
        await asyncio.sleep(0.1)
    assert broker.connected, "listener never connected"
    yield broker
    await broker.stop()


async def next_event(queue: asyncio.Queue, timeout: float = EVENT_TIMEOUT) -> dict:
    return await asyncio.wait_for(queue.get(), timeout=timeout)


async def event_matching(
    queue: asyncio.Queue, timeout: float = EVENT_TIMEOUT, **expected
) -> dict:
    """The next event matching `expected`, skipping any still in flight.

    A mutation made just before subscribing can still be delivered after, so
    asserting on the very first event received would be flaky.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    seen: list[dict] = []
    while True:
        remaining = deadline - loop.time()
        assert remaining > 0, f"no event matching {expected}; saw {seen}"
        event = await asyncio.wait_for(queue.get(), timeout=remaining)
        seen.append(event)
        if all(event.get(k) == v for k, v in expected.items()):
            return event


async def expect_silence(queue: asyncio.Queue, seconds: float = 2.0) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=seconds)


async def hold(world, who, seat_ids, key=None, body=None):
    headers = world.auth(who)
    if key:
        headers["Idempotency-Key"] = key
    return await world.client.post(
        "/api/holds",
        headers=headers,
        json=body or {"show_id": world.show_id, "seat_ids": seat_ids},
    )


async def db_seat_version(show_id: int) -> int:
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT seat_version FROM show WHERE id = :i"), {"i": show_id}
            )
        ).scalar_one()


# --------------------------------------------------------------- publisher


async def test_every_bump_notifies():
    """The two call-site sets must be identical, by construction.

    bump_and_notify is the only place BUMP_SEAT_VERSION is executed, so a
    mutation cannot advance the version without announcing it.
    """
    import pathlib

    offenders = []
    for path in pathlib.Path("app").rglob("*.py"):
        if path.as_posix().endswith(("booking/sql.py", "booking/events.py")):
            continue
        if "BUMP_SEAT_VERSION" in path.read_text():
            offenders.append(path.as_posix())
    assert offenders == [], f"bump outside events.py: {offenders}"

    source = inspect.getsource(events.bump_and_notify)
    assert "BUMP_SEAT_VERSION" in source and "pg_notify" in str(events.NOTIFY)


# ---------------------------------------------------------------- SSE flow


async def test_hold_emits_held_event(world, listening):
    seat = world.seat_ids[0]
    async with subscription(world.show_id) as queue:
        r = await hold(world, "alice", [seat])
        assert r.status_code == 201

        event = await event_matching(queue, status="held")
        assert event["show_id"] == world.show_id
        assert event["seat_ids"] == [seat]
        assert event["seat_version"] == await db_seat_version(world.show_id)


async def test_release_emits_available_event(world, listening):
    seat = world.seat_ids[1]
    r = await hold(world, "alice", [seat])
    group = r.json()["hold_group_id"]

    async with subscription(world.show_id) as queue:
        r = await world.client.delete(
            f"/api/holds/{group}", headers=world.auth("alice")
        )
        assert r.status_code == 200

        event = await event_matching(queue, status="available")
        assert event["seat_ids"] == [seat]


async def test_confirm_emits_booked_event(world, listening):
    seats = world.seat_ids[2:4]
    r = await hold(world, "alice", seats)
    group = r.json()["hold_group_id"]

    async with subscription(world.show_id) as queue:
        r = await world.client.post(
            f"/api/holds/{group}/confirm", headers=world.auth("alice")
        )
        assert r.status_code == 201
        event = await event_matching(queue, status="booked")
        assert sorted(event["seat_ids"]) == sorted(seats)


async def test_sweeper_expiry_emits_event(world, listening):
    seat = world.seat_ids[4]
    r = await hold(world, "alice", [seat])
    group = r.json()["hold_group_id"]

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE seat_claim SET expires_at = now() - interval '1 second'"
                " WHERE hold_group_id = CAST(:g AS uuid)"
            ),
            {"g": group},
        )

    async with subscription(world.show_id) as queue:
        async with SessionFactory() as session:
            assert await sweeper.sweep_expired_holds(session) == 1
        event = await event_matching(queue, status="available")
        assert event["seat_ids"] == [seat]


async def test_rolled_back_transaction_emits_nothing(world, listening):
    """pg_notify is transactional: a lost race announces nothing.

    Proved by ordering rather than by a timeout. Notifications reach the one
    LISTEN connection in commit order, so a sentinel committed AFTER the
    doomed transaction can only be the next event if that transaction emitted
    nothing. Waiting for silence alone would also pass against a broker that
    had died, which is the opposite of what this asserts.
    """
    contested, sentinel_seat = world.seat_ids[5], world.seat_ids[16]

    async with subscription(world.show_id) as queue:
        # Barrier. Draining alice's own event proves the pipe is flushed past
        # her commit, so nothing from before is still in flight below.
        assert (await hold(world, "alice", [contested])).status_code == 201
        await event_matching(queue, status="held", seat_ids=[contested])

        # The doomed transaction: bob loses the race and rolls back.
        r = await hold(world, "bob", [contested])
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "SEAT_UNAVAILABLE"

        # A commit that DOES announce, ordered strictly after the rollback.
        assert (await hold(world, "bob", [sentinel_seat])).status_code == 201

        event = await next_event(queue)
        assert event["seat_ids"] == [sentinel_seat], (
            f"a rolled-back transaction announced {event}"
        )
        assert event["status"] == "held"


async def test_two_subscribers_both_receive_and_others_do_not(world, listening):
    seat = world.seat_ids[6]
    other_show = world.show_id + 99_999

    async with subscription(world.show_id) as first:
        async with subscription(world.show_id) as second:
            async with subscription(other_show) as elsewhere:
                assert (await hold(world, "alice", [seat])).status_code == 201

                for queue in (first, second):
                    event = await event_matching(queue, status="held")
                    assert event["seat_ids"] == [seat]
                await expect_silence(elsewhere, seconds=1.0)


async def test_subscriber_is_deregistered_on_exit(world, listening):
    assert broker.subscriber_count(world.show_id) == 0
    async with subscription(world.show_id):
        assert broker.subscriber_count(world.show_id) == 1
    assert broker.subscriber_count(world.show_id) == 0


async def test_stream_response_is_configured_for_sse(world, listening):
    """The response object the route returns.

    Driven directly rather than over HTTP: httpx's ASGITransport buffers the
    whole body before returning, so it can never return from an endless
    generator. That is a limitation of the test transport, not the endpoint.
    """
    from app.booking import stream_router

    async with SessionFactory() as session:
        response = await stream_router.seatmap_stream(world.show_id, session)

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


async def test_stream_generator_registers_and_deregisters(world, listening):
    """The endpoint's own generator, including its finally block."""
    from app.booking.stream_router import _events

    seat = world.seat_ids[7]
    assert broker.subscriber_count(world.show_id) == 0

    stream = _events(world.show_id)
    first = await asyncio.wait_for(anext(stream), timeout=5)
    assert first.startswith(": connected")
    assert broker.subscriber_count(world.show_id) == 1

    # A real event reaches the wire as a data frame.
    assert (await hold(world, "alice", [seat])).status_code == 201
    frame = None
    while frame is None:
        chunk = await asyncio.wait_for(anext(stream), timeout=EVENT_TIMEOUT)
        if chunk.startswith("data: "):
            frame = chunk
    assert str(seat) in frame
    assert frame.endswith("\n\n"), "an SSE frame must be blank-line terminated"

    # Closing the generator is what a client disconnect looks like.
    await stream.aclose()
    assert broker.subscriber_count(world.show_id) == 0, "queue leaked on disconnect"


async def test_unknown_show_stream_is_404(world, listening):
    r = await world.client.get("/api/shows/987654/seatmap/stream")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


# ------------------------------------------------------------ idempotency


async def test_same_key_replays_one_hold(world):
    seats = world.seat_ids[8:10]
    first = await hold(world, "alice", seats, key="k-1")
    second = await hold(world, "alice", seats, key="k-1")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()

    async with engine.begin() as conn:
        groups = (
            await conn.execute(
                text("SELECT count(DISTINCT hold_group_id) FROM seat_claim")
            )
        ).scalar_one()
    assert groups == 1


async def test_same_key_different_body_is_409(world):
    first = await hold(world, "alice", world.seat_ids[10:11], key="k-2")
    assert first.status_code == 201

    second = await hold(
        world,
        "alice",
        None,
        key="k-2",
        body={"show_id": world.show_id, "seat_ids": world.seat_ids[11:12]},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


async def test_same_key_different_endpoint_is_409(world):
    r = await hold(world, "alice", world.seat_ids[12:13], key="k-3")
    group = r.json()["hold_group_id"]

    r = await world.client.post(
        f"/api/holds/{group}/confirm",
        headers={**world.auth("alice"), "Idempotency-Key": "k-3"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


async def test_key_from_a_rolled_back_operation_is_not_stored(world):
    seat = world.seat_ids[13]
    assert (await hold(world, "alice", [seat])).status_code == 201

    # bob loses the race; his transaction rolls back and must leave no key.
    losing = await hold(world, "bob", [seat], key="k-4")
    assert losing.status_code == 409

    async with engine.begin() as conn:
        stored = (
            await conn.execute(
                text("SELECT count(*) FROM idempotency_key WHERE key = 'k-4'")
            )
        ).scalar_one()
    assert stored == 0

    # And the key is still usable for a request that succeeds.
    retry = await hold(world, "bob", world.seat_ids[14:15], key="k-4")
    assert retry.status_code == 201


async def test_no_key_still_works(world):
    assert (await hold(world, "alice", world.seat_ids[15:16])).status_code == 201


# ----------------------------------------------------------------- errors


async def test_validation_error_uses_the_envelope(world):
    r = await world.client.post(
        "/api/holds",
        headers=world.auth("alice"),
        json={"show_id": "not-an-int"},
    )
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["details"], list)
    assert "field" in body["error"]["details"][0]
    assert "detail" not in body, "FastAPI's raw 422 shape escaped"


async def test_unhandled_exception_returns_internal_error(world, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("secret table 'user_account' does not exist")

    monkeypatch.setattr(service, "get_seat_map", boom)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30
    ) as client:
        r = await client.get(f"/api/shows/{world.show_id}/seatmap")

    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "Something went wrong on our side."
    assert len(body["error"]["details"]["correlation_id"]) == 12
    # Nothing about the internals may reach the client.
    assert "user_account" not in r.text
    assert "Traceback" not in r.text
    assert "RuntimeError" not in r.text


async def test_error_codes_are_defined_in_one_place():
    from app.core.errors import ErrorCode

    required = {
        "SEAT_UNAVAILABLE", "HOLD_EXPIRED", "HOLD_LIMIT_EXCEEDED", "OFFER_EXPIRED",
        "INVALID_SIGNATURE", "ALREADY_USED", "NOT_SOLD_OUT", "FORBIDDEN",
        "VALIDATION_ERROR", "NOT_FOUND", "CONFLICT", "INTERNAL_ERROR",
    }
    assert required <= {code.value for code in ErrorCode}
