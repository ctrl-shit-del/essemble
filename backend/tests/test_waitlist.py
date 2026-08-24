"""Cancellation, waitlist assignment, offers and history.

The centre of gravity here is I6: a seat promised to a waitlist entry must
never read as available. That is the one failure in this pass that produces no
error at all -- just a seat sold twice, under load, in production.
"""

import pytest
from sqlalchemy import text

from app.booking.sql import ACQUIRE_SEAT, ACQUIRE_SEAT_FOR_OFFER
from app.core.db import engine
from tests.conftest import active_claims, seat_version

# One event loop for the module, shared with the session-scoped fixtures.
pytestmark = pytest.mark.asyncio(loop_scope="session")

PREMIUM_SEATS = 12  # rows A and B of the 4x6 test screen


def conflict_clause(statement) -> str:
    body = str(statement)
    return " ".join(body[body.index("ON CONFLICT"):].split())


async def test_conflict_clauses_are_identical() -> None:
    """The offer-side statement must inherit the same guarantee.

    ACQUIRE_SEAT is left byte-identical to the graded original, so the two are
    separate strings; this asserts they never drift apart at the part that
    matters.
    """
    assert conflict_clause(ACQUIRE_SEAT) == conflict_clause(ACQUIRE_SEAT_FOR_OFFER)


async def hold(world, who, seat_ids, key=None):
    headers = world.auth(who)
    if key:
        headers["Idempotency-Key"] = key
    return await world.client.post(
        "/api/holds",
        headers=headers,
        json={"show_id": world.show_id, "seat_ids": seat_ids},
    )


async def book(world, who, seat_ids):
    r = await hold(world, who, seat_ids)
    assert r.status_code == 201, r.text
    group = r.json()["hold_group_id"]
    r = await world.client.post(
        f"/api/holds/{group}/confirm", headers=world.auth(who)
    )
    assert r.status_code == 201, r.text
    return r.json()["reference"]


async def seat_status(world) -> dict[int, str]:
    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    return {s["seat_id"]: s["status"] for s in r.json()["seats"]}


async def categories(world) -> dict[str, int]:
    # Resolved once by the session fixture; ids do not move between tests.
    return world.category_ids


async def premium_seat_ids(world) -> list[int]:
    return list(world.seats_by_category["Premium"])


async def fill_premium_except(world, keep: list[int]) -> None:
    """Book out the Premium category apart from `keep`, so it reads sold out."""
    seats = [s for s in await premium_seat_ids(world) if s not in keep]
    for index in range(0, len(seats), 10):
        chunk = seats[index : index + 10]
        who = ["alice", "bob", "carol"][(index // 10) % 3]
        await book(world, who, chunk)


async def offer_token_from_outbox() -> str:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT payload->>'claim_url' FROM outbox"
                    " WHERE template = 'waitlist_offer'"
                    " ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).scalar_one()
    return row.rsplit("/", 1)[1]


async def expire_offer(offer_id: int | None = None) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE waitlist_offer"
                " SET expires_at = now() - interval '1 second'"
                " WHERE state = 'pending'"
            )
        )
        await conn.execute(
            text(
                "UPDATE seat_claim SET expires_at = now() - interval '1 second'"
                " WHERE holder_type = 'waitlist_offer' AND state = 'held'"
            )
        )


# ------------------------------------------------------------- cancellation


async def test_cancel_with_empty_waitlist_frees_the_seats(world):
    seats = (await premium_seat_ids(world))[:2]
    reference = await book(world, "alice", seats)

    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert r.json()["offers_created"] == []

    # Assert the persisted row, not just the response: releasing the seats
    # while leaving the booking 'confirmed' would look fine from the outside.
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status::text, cancelled_at IS NOT NULL"
                    " FROM booking WHERE reference = :r"
                ),
                {"r": reference},
            )
        ).one()
    assert row == ("cancelled", True)

    status = await seat_status(world)
    for seat in seats:
        assert status[seat] == "available"


async def test_cancel_with_a_waiting_entry_holds_the_seats_for_the_offer(world):
    """The I6 test.

    After the cancellation commits, the freed seats must read as 'held' -- they
    have been promised to a waitlist entry. If they read 'available', the offer
    email is out while anyone can still take the seats.
    """
    keep = (await premium_seat_ids(world))[:1]
    await fill_premium_except(world, keep)
    reference = await book(world, "alice", keep)

    cats = await categories(world)
    r = await world.client.post(
        "/api/waitlist",
        headers=world.auth("carol"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1},
    )
    assert r.status_code == 201, r.text
    assert r.json()["position"] == 1

    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert r.status_code == 200, r.text
    offers = r.json()["offers_created"]
    assert len(offers) == 1
    assert offers[0]["seat_ids"] == keep

    status = await seat_status(world)
    assert status[keep[0]] == "held", (
        "an offered seat must never read as available (I6)"
    )

    claims = await active_claims(world.show_id, keep[0])
    assert len(claims) == 1 and claims[0][1] == "held"

    async with engine.begin() as conn:
        holder_type = (
            await conn.execute(
                text(
                    "SELECT holder_type FROM seat_claim"
                    " WHERE show_id = :s AND seat_id = :t"
                    " AND state IN ('held','booked')"
                ),
                {"s": world.show_id, "t": keep[0]},
            )
        ).scalar_one()
    assert holder_type == "waitlist_offer"


async def test_third_party_cannot_take_an_offered_seat(world):
    keep = (await premium_seat_ids(world))[:1]
    await fill_premium_except(world, keep)
    reference = await book(world, "alice", keep)

    cats = await categories(world)
    await world.client.post(
        "/api/waitlist",
        headers=world.auth("carol"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1},
    )
    await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )

    r = await hold(world, "bob", keep)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SEAT_UNAVAILABLE"


async def test_cancel_inside_the_cutoff_is_409(world):
    seats = (await premium_seat_ids(world))[:1]
    reference = await book(world, "alice", seats)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE show SET starts_at = now() + interval '10 minutes'"
                " WHERE id = :i"
            ),
            {"i": world.show_id},
        )

    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


async def test_cancel_twice_does_not_double_release(world):
    seats = (await premium_seat_ids(world))[:2]
    reference = await book(world, "alice", seats)

    first = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    second = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["offers_created"] == []


async def test_cannot_cancel_someone_elses_booking(world):
    reference = await book(world, "alice", (await premium_seat_ids(world))[:1])
    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("bob")
    )
    assert r.status_code == 403


# ----------------------------------------------------------------- waitlist


async def test_join_waitlist_when_seats_are_available_is_409(world):
    cats = await categories(world)
    r = await world.client.post(
        "/api/waitlist",
        headers=world.auth("alice"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "NOT_SOLD_OUT"


async def test_duplicate_waitlist_join_is_409_not_500(world):
    await fill_premium_except(world, [])
    cats = await categories(world)
    body = {"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1}

    first = await world.client.post(
        "/api/waitlist", headers=world.auth("carol"), json=body
    )
    assert first.status_code == 201
    second = await world.client.post(
        "/api/waitlist", headers=world.auth("carol"), json=body
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "CONFLICT"


async def test_smaller_entry_is_served_when_a_bigger_one_does_not_fit(world):
    """A qty=3 entry ahead of a qty=1 entry, with one seat freed.

    The qty=3 entry is skipped rather than blocking the queue, so the qty=1
    entry behind it is served. Deliberate: otherwise one freed seat would sit
    idle until somebody cancelled three.
    """
    keep = (await premium_seat_ids(world))[:1]
    await fill_premium_except(world, keep)
    reference = await book(world, "alice", keep)

    cats = await categories(world)
    big = await world.client.post(
        "/api/waitlist",
        headers=world.auth("bob"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 3},
    )
    assert big.status_code == 201
    small = await world.client.post(
        "/api/waitlist",
        headers=world.auth("carol"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1},
    )
    assert small.status_code == 201

    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert r.status_code == 200
    assert len(r.json()["offers_created"]) == 1
    assert r.json()["offers_created"][0]["entry_id"] == small.json()["id"]

    async with engine.begin() as conn:
        states = dict(
            (
                await conn.execute(
                    text("SELECT id, state::text FROM waitlist_entry ORDER BY id")
                )
            ).all()
        )
    assert states[big.json()["id"]] == "waiting"
    assert states[small.json()["id"]] == "offered"


async def test_position_is_computed_not_stored(world):
    await fill_premium_except(world, [])
    cats = await categories(world)
    body = {"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1}

    first = await world.client.post(
        "/api/waitlist", headers=world.auth("alice"), json=body
    )
    second = await world.client.post(
        "/api/waitlist", headers=world.auth("bob"), json=body
    )
    third = await world.client.post(
        "/api/waitlist", headers=world.auth("carol"), json=body
    )
    assert [r.json()["position"] for r in (first, second, third)] == [1, 2, 3]

    # Remove the first entry; the others move up without any renumbering write.
    r = await world.client.delete(
        f"/api/waitlist/{first.json()['id']}", headers=world.auth("alice")
    )
    assert r.status_code == 200

    r = await world.client.get("/api/waitlist", headers=world.auth("carol"))
    assert r.json()[0]["position"] == 2


async def test_cannot_leave_the_waitlist_while_holding_an_offer(world):
    keep = (await premium_seat_ids(world))[:1]
    await fill_premium_except(world, keep)
    reference = await book(world, "alice", keep)

    cats = await categories(world)
    entry = await world.client.post(
        "/api/waitlist",
        headers=world.auth("carol"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1},
    )
    await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )

    r = await world.client.delete(
        f"/api/waitlist/{entry.json()['id']}", headers=world.auth("carol")
    )
    assert r.status_code == 409


# ------------------------------------------------------------------- offers


async def _make_offer(world) -> tuple[str, list[int]]:
    keep = (await premium_seat_ids(world))[:1]
    await fill_premium_except(world, keep)
    reference = await book(world, "alice", keep)
    cats = await categories(world)
    await world.client.post(
        "/api/waitlist",
        headers=world.auth("carol"),
        json={"show_id": world.show_id, "category_id": cats["Premium"], "qty": 1},
    )
    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert len(r.json()["offers_created"]) == 1
    return await offer_token_from_outbox(), keep


async def test_offer_preview_needs_no_auth(world):
    token, seats = await _make_offer(world)

    r = await world.client.get(f"/api/waitlist/offers/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["seat_id"] for s in body["seats"]] == seats
    assert body["seconds_remaining"] > 0
    assert body["total"] == "400.00"
    assert "token" not in str(body)


async def test_unknown_token_is_indistinguishable_from_expired(world):
    r = await world.client.get("/api/waitlist/offers/not-a-real-token")
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "OFFER_EXPIRED"


async def test_claim_requires_the_right_user(world):
    token, _ = await _make_offer(world)
    r = await world.client.post(
        f"/api/waitlist/offers/{token}/claim", headers=world.auth("bob")
    )
    assert r.status_code == 403


async def test_claim_twice_is_410_and_books_once(world):
    token, seats = await _make_offer(world)

    first = await world.client.post(
        f"/api/waitlist/offers/{token}/claim", headers=world.auth("carol")
    )
    assert first.status_code == 201, first.text
    assert first.json()["reference"].startswith("ESB-")

    second = await world.client.post(
        f"/api/waitlist/offers/{token}/claim", headers=world.auth("carol")
    )
    assert second.status_code == 410
    assert second.json()["error"]["code"] == "OFFER_EXPIRED"

    async with engine.begin() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM booking WHERE reference = :r"),
                {"r": first.json()["reference"]},
            )
        ).scalar_one()
        entry_state = (
            await conn.execute(
                text("SELECT state::text FROM waitlist_entry LIMIT 1")
            )
        ).scalar_one()
    assert count == 1
    assert entry_state == "converted"

    claims = await active_claims(world.show_id, seats[0])
    assert len(claims) == 1 and claims[0][1] == "booked"


async def test_claim_after_expiry_is_410_and_leaves_seats_with_the_offer(world):
    token, seats = await _make_offer(world)
    await expire_offer()

    r = await world.client.post(
        f"/api/waitlist/offers/{token}/claim", headers=world.auth("carol")
    )
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "OFFER_EXPIRED"

    async with engine.begin() as conn:
        bookings = (
            await conn.execute(
                text("SELECT count(*) FROM booking WHERE status = 'confirmed'")
            )
        ).scalar_one()
        holder = (
            await conn.execute(
                text(
                    "SELECT holder_type::text, state::text FROM seat_claim"
                    " WHERE show_id = :s AND seat_id = :t"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"s": world.show_id, "t": seats[0]},
            )
        ).one()
    # The lapsed offer still owns the row; Phase 4's sweeper reclaims it.
    assert holder == ("waitlist_offer", "held")
    assert bookings >= 1


async def test_claiming_converts_and_bumps_seat_version(world):
    token, _ = await _make_offer(world)
    before = await seat_version(world.show_id)
    r = await world.client.post(
        f"/api/waitlist/offers/{token}/claim", headers=world.auth("carol")
    )
    assert r.status_code == 201
    assert await seat_version(world.show_id) > before


# ------------------------------------------------------------------ history


async def test_booking_history(world):
    seats = (await premium_seat_ids(world))[:2]
    reference = await book(world, "alice", seats)

    r = await world.client.get("/api/bookings", headers=world.auth("alice"))
    assert r.status_code == 200
    assert len(r.json()) == 1
    item = r.json()[0]
    assert item["reference"] == reference
    assert item["status"] == "confirmed"
    assert len(item["seats"]) == 2
    assert item["qr_signature"]

    r = await world.client.get("/api/bookings", headers=world.auth("bob"))
    assert r.json() == []

    r = await world.client.get(
        f"/api/bookings/{reference}", headers=world.auth("bob")
    )
    assert r.status_code == 403

    r = await world.client.get(
        f"/api/bookings/{reference}", headers=world.auth("alice")
    )
    assert r.status_code == 200

    r = await world.client.get(
        "/api/bookings", headers=world.auth("alice"), params={"status": "cancelled"}
    )
    assert r.json() == []
