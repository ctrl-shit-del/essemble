"""Sweeper, outbox dispatcher, QR and check-in.

The sweep functions are called directly. Nothing here sleeps or waits on an
APScheduler interval -- rows are placed in the past by moving expires_at, which
is the same thing the passage of time would do, only immediately.
"""

import pytest
from sqlalchemy import text

from app.booking import assignment, cancellation
from app.core.db import SessionFactory, engine
from app.notifications import email, qr
from app.workers import outbox as outbox_worker
from app.workers import sweeper
from tests.conftest import active_claims, seat_version

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --------------------------------------------------------------- helpers


async def hold(world, who, seat_ids):
    return await world.client.post(
        "/api/holds",
        headers=world.auth(who),
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
    return r.json()["reference"], group


async def seat_status(world):
    r = await world.client.get(f"/api/shows/{world.show_id}/seatmap")
    return {s["seat_id"]: s["status"] for s in r.json()["seats"]}


async def sql(statement, **params):
    """Run a statement; return rows when there are any, else None."""
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None


async def scalar(statement, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(statement), params)).scalar_one_or_none()


async def run_sweep(func):
    async with SessionFactory() as session:
        return await func(session)


async def fill_premium_except(world, keep):
    seats = [s for s in world.seats_by_category["Premium"] if s not in keep]
    for index in range(0, len(seats), 10):
        chunk = seats[index : index + 10]
        who = ["alice", "bob", "carol"][(index // 10) % 3]
        await book(world, who, chunk)


async def make_offer(world, waiter="carol"):
    """Cancel a booking with someone waiting, producing a live offer."""
    keep = world.seats_by_category["Premium"][:1]
    await fill_premium_except(world, keep)
    reference, _ = await book(world, "alice", keep)
    await world.client.post(
        "/api/waitlist",
        headers=world.auth(waiter),
        json={
            "show_id": world.show_id,
            "category_id": world.category_ids["Premium"],
            "qty": 1,
        },
    )
    r = await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    assert len(r.json()["offers_created"]) == 1
    return r.json()["offers_created"][0], keep


async def expire_offer_claims():
    """Push the offer and its seat claims into the past, without sweeping."""
    await sql(
        "UPDATE seat_claim SET expires_at = now() - interval '1 second'"
        " WHERE holder_type = 'waitlist_offer' AND state = 'held'"
    )
    await sql(
        "UPDATE waitlist_offer SET expires_at = now() - interval '1 second'"
        " WHERE state = 'pending'"
    )


# ------------------------------------------------------- sweep 1: holds


async def test_expired_hold_is_available_before_the_sweep_runs(world):
    seat = world.seat_ids[0]
    r = await hold(world, "alice", [seat])
    group = r.json()["hold_group_id"]

    await sql(
        "UPDATE seat_claim SET expires_at = now() - interval '1 second'"
        " WHERE hold_group_id = CAST(:g AS uuid)",
        g=group,
    )

    # Nothing has swept. The seat is already available, because expiry is
    # authoritative via the timestamp.
    assert (await seat_status(world))[seat] == "available"
    assert (await active_claims(world.show_id, seat))[0][1] == "held"

    before = await seat_version(world.show_id)
    assert await run_sweep(sweeper.sweep_expired_holds) == 1

    state = await scalar(
        "SELECT state::text FROM seat_claim WHERE hold_group_id = CAST(:g AS uuid)",
        g=group,
    )
    assert state == "expired"
    assert await seat_version(world.show_id) > before
    assert (await seat_status(world))[seat] == "available"


async def test_sweep_leaves_live_holds_alone(world):
    seat = world.seat_ids[1]
    await hold(world, "alice", [seat])
    assert await run_sweep(sweeper.sweep_expired_holds) == 0
    assert (await seat_status(world))[seat] == "held"


async def test_two_concurrent_ticks_do_not_double_process(world):
    """SKIP LOCKED: whatever one tick takes, the other steps over."""
    r = await hold(world, "alice", [world.seat_ids[2]])
    await sql(
        "UPDATE seat_claim SET expires_at = now() - interval '1 second'"
        " WHERE hold_group_id = CAST(:g AS uuid)",
        g=r.json()["hold_group_id"],
    )

    first = await run_sweep(sweeper.sweep_expired_holds)
    second = await run_sweep(sweeper.sweep_expired_holds)
    assert (first, second) == (1, 0)

    swept = await scalar(
        "SELECT count(*) FROM seat_claim WHERE state = 'expired'"
    )
    assert swept == 1


# ------------------------------------------------- sweep 2: lapsed offers


async def test_lapsed_offer_cascades_to_the_next_entry(world):
    offer, seats = await make_offer(world, waiter="carol")

    # A second person is waiting behind the offer holder.
    r = await world.client.post(
        "/api/waitlist",
        headers=world.auth("bob"),
        json={
            "show_id": world.show_id,
            "category_id": world.category_ids["Premium"],
            "qty": 1,
        },
    )
    assert r.status_code == 201

    await expire_offer_claims()
    offers_before = await scalar("SELECT count(*) FROM waitlist_offer")
    assert await run_sweep(sweeper.sweep_lapsed_offers) == 1

    states = dict(await sql("SELECT id, state::text FROM waitlist_offer ORDER BY id"))
    assert states[offer["offer_id"]] == "expired"
    assert await scalar("SELECT count(*) FROM waitlist_offer") == offers_before + 1

    entry_states = dict(
        await sql("SELECT user_id, state::text FROM waitlist_entry ORDER BY id")
    )
    assert "declined" in entry_states.values()
    assert "offered" in entry_states.values()

    # The seats never became generally available: they moved from one offer
    # straight to the next.
    assert (await seat_status(world))[seats[0]] == "held"
    holder = await scalar(
        "SELECT holder_type::text FROM seat_claim"
        " WHERE show_id = :s AND seat_id = :t AND state IN ('held','booked')",
        s=world.show_id,
        t=seats[0],
    )
    assert holder == "waitlist_offer"

    assert await scalar(
        "SELECT count(*) FROM outbox WHERE template = 'waitlist_offer'"
    ) == 2


async def test_lapsed_offer_with_no_next_entry_releases_the_seats(world):
    _offer, seats = await make_offer(world, waiter="carol")
    await expire_offer_claims()

    assert await run_sweep(sweeper.sweep_lapsed_offers) == 1

    assert (await seat_status(world))[seats[0]] == "available"
    assert await active_claims(world.show_id, seats[0]) == []
    entry_state = await scalar("SELECT state::text FROM waitlist_entry LIMIT 1")
    assert entry_state == "declined"


async def test_offer_claimed_just_before_the_sweep_wins(world):
    offer, seats = await make_offer(world, waiter="carol")

    token_url = await scalar(
        "SELECT payload->>'claim_url' FROM outbox"
        " WHERE template = 'waitlist_offer' ORDER BY created_at DESC LIMIT 1"
    )
    token = token_url.rsplit("/", 1)[1]
    r = await world.client.post(
        f"/api/waitlist/offers/{token}/claim", headers=world.auth("carol")
    )
    assert r.status_code == 201

    # Age the offer row as if its deadline had passed a moment after the claim.
    await sql(
        "UPDATE waitlist_offer SET expires_at = now() - interval '1 second'"
    )
    await run_sweep(sweeper.sweep_lapsed_offers)
    await run_sweep(sweeper.sweep_orphaned_offers)

    state = await scalar(
        "SELECT state::text FROM waitlist_offer WHERE id = :i", i=offer["offer_id"]
    )
    assert state == "claimed", "a claim that landed before the sweep must win"

    entry_state = await scalar("SELECT state::text FROM waitlist_entry LIMIT 1")
    assert entry_state == "converted"
    assert (await seat_status(world))[seats[0]] == "booked"


# --------------------------------------------- sweep 3: orphaned offers


async def test_orphaned_pending_offer_is_caught(world):
    offer, seats = await make_offer(world, waiter="carol")

    # Simulate a crash between the claims going and the offer being marked:
    # the claims are gone, so sweep 2 can never see this offer.
    await sql(
        "DELETE FROM seat_claim WHERE holder_type = 'waitlist_offer'"
        " AND holder_id = :i",
        i=offer["offer_id"],
    )
    await sql(
        "UPDATE waitlist_offer SET expires_at = now() - interval '1 second'"
        " WHERE id = :i",
        i=offer["offer_id"],
    )

    assert await run_sweep(sweeper.sweep_lapsed_offers) == 0, (
        "sweep 2 is driven by claim rows; it cannot see this"
    )
    assert await run_sweep(sweeper.sweep_orphaned_offers) == 1

    state = await scalar(
        "SELECT state::text FROM waitlist_offer WHERE id = :i", i=offer["offer_id"]
    )
    assert state == "expired"
    entry_state = await scalar("SELECT state::text FROM waitlist_entry LIMIT 1")
    assert entry_state == "declined"
    assert (await seat_status(world))[seats[0]] == "available"


async def test_run_tick_survives_a_failing_sweep(world, monkeypatch):
    """A broken sweep must not stop the others, now or next tick."""

    async def boom(session):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(sweeper, "sweep_expired_holds", boom)
    results = await sweeper.run_tick()
    assert results["expired_holds"] == -1
    assert results["lapsed_offers"] >= 0
    assert results["orphaned_offers"] >= 0


# ------------------------------------------------------------- outbox


async def test_outbox_delivers_and_marks_sent(world):
    await book(world, "alice", world.seat_ids[3:5])
    pending = await scalar("SELECT count(*) FROM outbox WHERE state = 'pending'")
    assert pending == 1

    async with SessionFactory() as session:
        result = await outbox_worker.dispatch_once(session)
    assert result == {"sent": 1, "failed": 0}

    row = (
        await sql("SELECT state::text, sent_at IS NOT NULL FROM outbox LIMIT 1")
    )[0]
    assert row == ("sent", True)


async def test_outbox_failure_retries_then_gives_up(world, monkeypatch):
    reference, _ = await book(world, "alice", world.seat_ids[5:6])

    def explode(template, to_email, payload):
        raise RuntimeError("provider down")

    monkeypatch.setattr(outbox_worker.email, "deliver", explode)

    for attempt in range(1, 6):
        # Backoff would otherwise defer the row; age it so the next attempt is
        # due immediately.
        await sql("UPDATE outbox SET created_at = now() - interval '1 hour'")
        async with SessionFactory() as session:
            result = await outbox_worker.dispatch_once(session)
        assert result == {"sent": 0, "failed": 1}

        state, attempts, last_error = (
            await sql("SELECT state::text, attempts, last_error FROM outbox LIMIT 1")
        )[0]
        assert attempts == attempt
        assert "provider down" in last_error
        assert state == ("failed" if attempt >= 5 else "pending")

    # Exhausted rows are not picked up again.
    await sql("UPDATE outbox SET created_at = now() - interval '1 hour'")
    async with SessionFactory() as session:
        assert await outbox_worker.dispatch_once(session) == {"sent": 0, "failed": 0}

    # And the booking is untouched by any of it.
    status = await scalar(
        "SELECT status::text FROM booking WHERE reference = :r", r=reference
    )
    assert status == "confirmed"


async def test_outbox_backoff_defers_a_freshly_failed_row(world, monkeypatch):
    await book(world, "alice", world.seat_ids[6:7])

    def explode(template, to_email, payload):
        raise RuntimeError("provider down")

    monkeypatch.setattr(outbox_worker.email, "deliver", explode)
    async with SessionFactory() as session:
        await outbox_worker.dispatch_once(session)

    # Start the backoff window where this test means it to start. The booking
    # and the first dispatch above spend most of a second in round trips to a
    # remote database, so measuring 2^attempts from the original created_at
    # left ~0.3s of the window and the row came due again under load. Pinning
    # the timestamp tests the backoff formula rather than the network.
    await sql("UPDATE outbox SET created_at = now()")

    # attempts=1 -> not due again for 2 seconds.
    async with SessionFactory() as session:
        assert await outbox_worker.dispatch_once(session) == {"sent": 0, "failed": 0}


# ---------------------------------------------------------------- QR


async def test_qr_payload_round_trips(world):
    reference, _ = await book(world, "alice", world.seat_ids[7:8])
    signature = await scalar(
        "SELECT qr_signature FROM booking WHERE reference = :r", r=reference
    )

    payload = qr.build_payload(reference)
    assert payload == f"{reference}.{signature}"
    assert qr.verify_payload(payload) == reference
    assert len(qr.png_bytes(payload)) > 100


async def test_tampered_qr_fails_verification(world):
    reference, _ = await book(world, "alice", world.seat_ids[8:9])
    payload = qr.build_payload(reference)
    signature = payload.split(".")[1]

    assert qr.verify_payload(f"ESB-FAKE01.{signature}") is None
    assert qr.verify_payload(f"{reference}.{'0' * 16}") is None
    assert qr.verify_payload(reference) is None, "a bare reference is not enough"
    assert qr.verify_payload("") is None


async def test_confirmation_email_embeds_the_qr(world):
    reference, _ = await book(world, "alice", world.seat_ids[9:10])
    payload = (
        await sql("SELECT template, to_email, payload FROM outbox LIMIT 1")
    )[0]
    rendered = email.render(payload[0], payload[1], payload[2])

    assert "cid:essemble-qr" in rendered.html
    assert rendered.qr_payload == qr.build_payload(reference)
    assert rendered.inline_images["essemble-qr"][:4] == b"\x89PNG"
    assert reference in rendered.html


# ------------------------------------------------------------- check-in


async def test_checkin_valid_then_already_used(world):
    reference, _ = await book(world, "alice", world.seat_ids[10:12])
    payload = qr.build_payload(reference)

    r = await world.client.post(
        "/api/checkin/verify",
        headers=world.auth("admin"),
        json={"qr_payload": payload},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"] == "VALID"
    assert body["reference"] == reference
    assert body["customer_name"] == "Alice"
    assert len(body["seats"]) == 2
    first_time = body["checked_in_at"]

    again = await world.client.post(
        "/api/checkin/verify",
        headers=world.auth("admin"),
        json={"qr_payload": payload},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_USED"
    assert again.json()["error"]["details"]["checked_in_at"][:19] == first_time[:19]


async def test_checkin_rejects_a_tampered_payload(world):
    reference, _ = await book(world, "alice", world.seat_ids[12:13])

    for bad in (reference, f"{reference}.{'0' * 16}", "nonsense", ""):
        r = await world.client.post(
            "/api/checkin/verify",
            headers=world.auth("admin"),
            json={"qr_payload": bad},
        )
        assert r.status_code == 400, bad
        assert r.json()["error"]["code"] == "INVALID_SIGNATURE"


async def test_checkin_requires_owning_the_venue(world):
    """Admin role is necessary, not sufficient."""
    from app.core.security import hash_password

    reference, _ = await book(world, "alice", world.seat_ids[13:14])

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO user_account (email, password_hash, name, role)
                   VALUES ('rival@t.dev', :p, 'Rival', 'admin')
                   ON CONFLICT (email) DO UPDATE SET password_hash = :p"""
            ),
            {"p": hash_password("essemble123")},
        )

    r = await world.client.post(
        "/api/auth/login",
        json={"email": "rival@t.dev", "password": "essemble123"},
    )
    rival = r.json()["access_token"]

    r = await world.client.post(
        "/api/checkin/verify",
        headers={"Authorization": f"Bearer {rival}"},
        json={"qr_payload": qr.build_payload(reference)},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"

    # The failed attempt must not have consumed the ticket.
    still_open = await scalar(
        "SELECT checked_in_at IS NULL FROM booking WHERE reference = :r",
        r=reference,
    )
    assert still_open is True


async def test_checkin_requires_admin_role(world):
    reference, _ = await book(world, "alice", world.seat_ids[14:15])
    r = await world.client.post(
        "/api/checkin/verify",
        headers=world.auth("alice"),
        json={"qr_payload": qr.build_payload(reference)},
    )
    assert r.status_code == 403


async def test_cancelled_booking_cannot_check_in(world):
    reference, _ = await book(world, "alice", world.seat_ids[15:16])
    await world.client.post(
        f"/api/bookings/{reference}/cancel", headers=world.auth("alice")
    )
    r = await world.client.post(
        "/api/checkin/verify",
        headers=world.auth("admin"),
        json={"qr_payload": qr.build_payload(reference)},
    )
    assert r.status_code == 403


# ------------------------------------------------- the shared cascade


async def test_cancellation_and_sweeper_share_one_cascade():
    """Both paths must call assignment.assign_freed_seats, not a copy."""
    import inspect

    assert "assignment.assign_freed_seats" in inspect.getsource(
        cancellation.cancel_booking
    )
    assert "assignment.assign_freed_seats" in inspect.getsource(
        sweeper.sweep_lapsed_offers
    )
    assert "assignment.assign_freed_seats" in inspect.getsource(
        sweeper.sweep_orphaned_offers
    )
    # And there is exactly one definition of it.
    assert inspect.getsource(assignment.assign_freed_seats).count(
        "async def assign_freed_seats"
    ) == 1
