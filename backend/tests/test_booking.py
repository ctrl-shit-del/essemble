"""Hold acquisition, confirmation and the seat map.

Every test here exercises the invariants directly rather than the happy path:
what matters is that a seat cannot be taken twice, that an expired hold is
gone whether or not anything swept it, and that a failed multi-seat hold
leaves nothing behind.
"""

from decimal import Decimal

import pytest

from tests.conftest import (
    active_claims,
    booking_count,
    expire_group,
    seat_version,
)

# One event loop for the module, shared with the session-scoped fixtures.
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def hold(world, who: str, seat_ids: list[int], key: str | None = None):
    headers = world.auth(who)
    if key:
        headers["Idempotency-Key"] = key
    return await world.client.post(
        "/api/holds",
        headers=headers,
        json={"show_id": world.show_id, "seat_ids": seat_ids},
    )


async def confirm(world, who: str, group_id: str, key: str | None = None):
    headers = world.auth(who)
    if key:
        headers["Idempotency-Key"] = key
    return await world.client.post(
        f"/api/holds/{group_id}/confirm", headers=headers
    )


# --------------------------------------------------------------- acquisition


async def test_hold_on_a_booked_seat_is_rejected(world):
    seat = world.seat_ids[0]

    r = await hold(world, "alice", [seat])
    assert r.status_code == 201
    group = r.json()["hold_group_id"]
    assert (await confirm(world, "alice", group)).status_code == 201

    before = await active_claims(world.show_id, seat)

    r = await hold(world, "bob", [seat])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SEAT_UNAVAILABLE"
    assert r.json()["error"]["details"]["seat_ids"] == [seat]

    after = await active_claims(world.show_id, seat)
    assert after == before, "the existing booked claim was modified"
    assert len(after) == 1 and after[0][1] == "booked"


async def test_hold_on_a_live_held_seat_is_rejected(world):
    seat = world.seat_ids[1]

    r = await hold(world, "alice", [seat])
    assert r.status_code == 201
    alice_group = r.json()["hold_group_id"]

    r = await hold(world, "bob", [seat])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SEAT_UNAVAILABLE"

    claims = await active_claims(world.show_id, seat)
    assert len(claims) == 1
    r = await world.client.get(f"/api/holds/{alice_group}", headers=world.auth("alice"))
    assert r.status_code == 200, "alice's hold should be untouched"


async def test_expired_but_unswept_hold_is_taken_over(world):
    seat = world.seat_ids[2]

    r = await hold(world, "alice", [seat])
    alice_group = r.json()["hold_group_id"]

    # No sweeper runs in this test. The claim row is still state='held'.
    await expire_group(alice_group)

    r = await hold(world, "bob", [seat])
    assert r.status_code == 201, r.text
    bob_group = r.json()["hold_group_id"]
    assert bob_group != alice_group

    claims = await active_claims(world.show_id, seat)
    assert len(claims) == 1, "takeover must not leave two active claims"
    assert claims[0][1] == "held"

    # Alice's group is now 404, not 410. The mandated acquisition statement
    # takes the seat over with DO UPDATE, which rewrites hold_group_id on the
    # SAME row -- so once a lapsed hold is taken over, no row bearing her group
    # survives to report itself as expired. An untaken lapse still answers 410
    # (see test_lapsed_hold_not_taken_over_reports_410).
    r = await world.client.get(f"/api/holds/{alice_group}", headers=world.auth("alice"))
    assert r.status_code == 404


async def test_lapsed_hold_not_taken_over_reports_410(world):
    """The other half of the pair above: nobody took it, so the row remains."""
    seat = world.seat_ids[22]
    group = (await hold(world, "alice", [seat])).json()["hold_group_id"]
    await expire_group(group)

    r = await world.client.get(f"/api/holds/{group}", headers=world.auth("alice"))
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "HOLD_EXPIRED"


async def test_multi_seat_hold_is_all_or_nothing(world):
    taken, free_a, free_b = world.seat_ids[3], world.seat_ids[4], world.seat_ids[5]

    assert (await hold(world, "alice", [taken])).status_code == 201

    r = await hold(world, "bob", [free_a, taken, free_b])
    assert r.status_code == 409
    assert r.json()["error"]["details"]["seat_ids"] == [taken]

    for seat in (free_a, free_b):
        assert await active_claims(world.show_id, seat) == [], (
            f"seat {seat} was left held after a failed group"
        )

    # And they are genuinely still takeable.
    assert (await hold(world, "bob", [free_a, free_b])).status_code == 201


async def test_hold_reports_every_lost_seat(world):
    a, b, c = world.seat_ids[6], world.seat_ids[7], world.seat_ids[8]
    assert (await hold(world, "alice", [a, b])).status_code == 201

    r = await hold(world, "bob", [a, b, c])
    assert r.status_code == 409
    assert r.json()["error"]["details"]["seat_ids"] == sorted([a, b])


async def test_one_live_hold_group_per_user_per_show(world):
    assert (await hold(world, "alice", [world.seat_ids[9]])).status_code == 201
    r = await hold(world, "alice", [world.seat_ids[10]])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "HOLD_LIMIT_EXCEEDED"


async def test_seats_from_another_screen_are_rejected(world):
    r = await world.client.post(
        "/api/holds",
        headers=world.auth("alice"),
        json={"show_id": world.show_id, "seat_ids": [999999]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_duplicate_seat_ids_are_rejected(world):
    seat = world.seat_ids[0]
    r = await world.client.post(
        "/api/holds",
        headers=world.auth("alice"),
        json={"show_id": world.show_id, "seat_ids": [seat, seat]},
    )
    assert r.status_code == 422


# --------------------------------------------------------------- confirmation


async def test_confirm_within_ttl_books_the_seats(world):
    seats = world.seat_ids[11:13]
    r = await hold(world, "alice", seats)
    group = r.json()["hold_group_id"]

    r = await confirm(world, "alice", group)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["reference"].startswith("ESB-") and len(body["reference"]) == 10
    assert len(body["qr_signature"]) == 16
    # Seats 12 and 13 straddle the Premium/Standard boundary on this layout,
    # so assert against the prices actually returned rather than a constant.
    assert body["total"] == "650.00"
    assert sum(Decimal(s["price"]) for s in body["seats"]) == Decimal(body["total"])

    for seat in seats:
        claims = await active_claims(world.show_id, seat)
        assert len(claims) == 1
        assert claims[0][1] == "booked"
        assert claims[0][3] is None, "a booked claim must not keep an expiry"


async def test_confirm_after_expiry_is_410_and_writes_nothing(world):
    seats = world.seat_ids[13:15]
    r = await hold(world, "alice", seats)
    group = r.json()["hold_group_id"]

    await expire_group(group)
    before = await booking_count()

    r = await confirm(world, "alice", group)
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "HOLD_EXPIRED"
    assert await booking_count() == before, "a booking was created for a dead hold"


async def test_confirm_twice_with_one_key_replays(world):
    seats = world.seat_ids[15:17]
    r = await hold(world, "alice", seats)
    group = r.json()["hold_group_id"]

    first = await confirm(world, "alice", group, key="confirm-once")
    assert first.status_code == 201
    before = await booking_count()

    second = await confirm(world, "alice", group, key="confirm-once")
    assert second.status_code == 201
    assert second.json() == first.json(), "replay returned a different body"
    assert await booking_count() == before == 1


async def test_confirm_twice_without_a_key_is_410(world):
    seats = world.seat_ids[17:19]
    group = (await hold(world, "alice", seats)).json()["hold_group_id"]

    assert (await confirm(world, "alice", group)).status_code == 201
    r = await confirm(world, "alice", group)
    assert r.status_code == 410
    assert await booking_count() == 1


async def test_confirming_someone_elses_hold_is_403(world):
    group = (await hold(world, "alice", [world.seat_ids[19]])).json()["hold_group_id"]
    r = await confirm(world, "bob", group)
    assert r.status_code == 403
    assert await booking_count() == 0


async def test_holds_are_idempotent_on_key(world):
    seats = world.seat_ids[20:22]
    first = await hold(world, "alice", seats, key="hold-once")
    assert first.status_code == 201
    second = await hold(world, "alice", seats, key="hold-once")
    assert second.status_code == 201
    assert second.json() == first.json()


# -------------------------------------------------------------------- seatmap


async def test_seatmap_shows_expired_hold_as_available(world):
    seat = world.seat_ids[0]
    group = (await hold(world, "alice", [seat])).json()["hold_group_id"]

    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    status_by_seat = {s["seat_id"]: s["status"] for s in r.json()["seats"]}
    assert status_by_seat[seat] == "held"

    # Expire it, run no sweeper at all, and read again.
    await expire_group(group)

    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    status_by_seat = {s["seat_id"]: s["status"] for s in r.json()["seats"]}
    assert status_by_seat[seat] == "available", (
        "expiry must be authoritative via expires_at, not via the sweeper"
    )


async def test_seatmap_reports_booked(world):
    seat = world.seat_ids[1]
    group = (await hold(world, "alice", [seat])).json()["hold_group_id"]
    await confirm(world, "alice", group)

    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    status_by_seat = {s["seat_id"]: s["status"] for s in r.json()["seats"]}
    assert status_by_seat[seat] == "booked"


async def test_seatmap_since_returns_304(world):
    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    assert r.status_code == 200
    version = r.json()["seat_version"]

    r = await world.client.get(
        f"/api/shows/{world.show_id}/seatmap", params={"since": version}
    )
    assert r.status_code == 304
    assert not r.content

    await hold(world, "alice", [world.seat_ids[2]])
    r = await world.client.get(
        f"/api/shows/{world.show_id}/seatmap", params={"since": version}
    )
    assert r.status_code == 200
    assert r.json()["seat_version"] > version


async def test_seatmap_carries_this_shows_prices(world):
    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    body = r.json()
    assert body["event_title"] == "Test Feature"
    assert body["venue_name"] == "Test Venue"
    assert body["screen_name"] == "Audi 1"
    prices = {c["name"]: c["price"] for c in body["categories"]}
    assert prices == {"Premium": "400.00", "Standard": "250.00"}
    assert len(body["seats"]) == 24


# --------------------------------------------------------------------- release


async def test_delete_hold_frees_the_seat_and_bumps_version(world):
    seat = world.seat_ids[3]
    group = (await hold(world, "alice", [seat])).json()["hold_group_id"]
    version_after_hold = await seat_version(world.show_id)

    r = await world.client.delete(f"/api/holds/{group}", headers=world.auth("alice"))
    assert r.status_code == 200
    assert r.json()["released_seat_ids"] == [seat]

    assert await seat_version(world.show_id) > version_after_hold
    assert await active_claims(world.show_id, seat) == []

    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    status_by_seat = {s["seat_id"]: s["status"] for s in r.json()["seats"]}
    assert status_by_seat[seat] == "available"

    # And the seat is immediately takeable by someone else.
    assert (await hold(world, "bob", [seat])).status_code == 201


async def test_delete_hold_is_idempotent(world):
    group = (await hold(world, "alice", [world.seat_ids[4]])).json()["hold_group_id"]
    first = await world.client.delete(f"/api/holds/{group}", headers=world.auth("alice"))
    second = await world.client.delete(f"/api/holds/{group}", headers=world.auth("alice"))
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["already_released"] is True


async def test_deleting_someone_elses_hold_is_403(world):
    group = (await hold(world, "alice", [world.seat_ids[5]])).json()["hold_group_id"]
    r = await world.client.delete(f"/api/holds/{group}", headers=world.auth("bob"))
    assert r.status_code == 403
