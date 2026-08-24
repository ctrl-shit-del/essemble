"""Background sweeper.

Expiry is authoritative via seat_claim.expires_at and waitlist_offer.
expires_at. Every read filters on the timestamp and every acquisition can
take over an expired claim, so a hold or offer is functionally expired the
instant its timestamp passes, whether or not this worker is running. The
sweeper only MATERIALISES side effects: the state transition, the
seat_version bump, and the waitlist cascade. The app is deployed on a free
tier where the instance sleeps; correctness must never depend on this
worker having run.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking import assignment
from app.booking.events import bump_and_notify
from app.core.db import SessionFactory

logger = logging.getLogger("essemble.sweeper")

BATCH = 200

#: When run_tick last completed, in this process. Read by GET /api/health so
#: a hosted instance can show that the worker is actually running rather than
#: merely configured. Deliberately in-process: persisting it would mean a
#: write on every tick to answer a question only this process can be asked.
last_run_at: datetime | None = None

# SKIP LOCKED throughout, so two ticks (or two instances) never process the
# same row twice: the second transaction steps over rows the first has locked
# rather than blocking on them.

EXPIRE_USER_HOLDS = text(
    """
    UPDATE seat_claim SET state = 'expired'
    WHERE id IN (
        SELECT id FROM seat_claim
        WHERE state = 'held' AND holder_type = 'user' AND expires_at <= now()
        ORDER BY expires_at LIMIT :batch
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, show_id, seat_id
    """
)

EXPIRE_OFFER_HOLDS = text(
    """
    UPDATE seat_claim SET state = 'expired'
    WHERE id IN (
        SELECT id FROM seat_claim
        WHERE state = 'held' AND holder_type = 'waitlist_offer'
          AND expires_at <= now()
        ORDER BY expires_at LIMIT :batch
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, show_id, seat_id, holder_id
    """
)

#: Guarded on state='pending': an offer claimed between its expiry timestamp
#: and this sweep must win. The claim already booked the seats.
MARK_OFFER_EXPIRED = text(
    """
    UPDATE waitlist_offer SET state = 'expired'
    WHERE id = :offer_id AND state = 'pending'
    RETURNING entry_id, seat_ids
    """
)

DECLINE_ENTRY = text(
    """
    UPDATE waitlist_entry SET state = 'declined'
    WHERE id = :entry_id AND state = 'offered'
    """
)

#: Offers whose deadline passed while their claims are already gone -- a crash
#: between the two leaves state that sweep 2 can never see, because sweep 2 is
#: driven by claim rows.
ORPHANED_OFFERS = text(
    """
    SELECT id FROM waitlist_offer
    WHERE state = 'pending' AND expires_at <= now()
    ORDER BY expires_at LIMIT :batch
    FOR UPDATE SKIP LOCKED
    """
)

RELEASE_OFFER_CLAIMS = text(
    """
    UPDATE seat_claim SET state = 'released', expires_at = NULL
    WHERE holder_type = 'waitlist_offer' AND holder_id = :offer_id
      AND state IN ('held','booked')
    RETURNING show_id, seat_id
    """
)

SHOW_OF_ENTRY = text("SELECT show_id FROM waitlist_entry WHERE id = :entry_id")


async def sweep_expired_holds(session: AsyncSession) -> int:
    """Sweep 1: ordinary user holds whose TTL has passed."""
    rows = (await session.execute(EXPIRE_USER_HOLDS, {"batch": BATCH})).all()
    by_show: dict[int, list[int]] = {}
    for row in rows:
        by_show.setdefault(row.show_id, []).append(row.seat_id)
    for show_id, seat_ids in by_show.items():
        await bump_and_notify(session, show_id, (seat_ids, "available"))
    await session.commit()
    if rows:
        logger.info("swept %d expired user hold(s)", len(rows))
    return len(rows)


async def sweep_lapsed_offers(session: AsyncSession) -> int:
    """Sweep 2: offers whose seats have just expired.

    The freed seats go straight back through the same cascade a cancellation
    uses, so the next fitting entry is served without the seats ever becoming
    generally available.
    """
    rows = (await session.execute(EXPIRE_OFFER_HOLDS, {"batch": BATCH})).all()
    if not rows:
        await session.commit()
        return 0

    by_offer: dict[int, list[int]] = {}
    show_of_offer: dict[int, int] = {}
    for row in rows:
        by_offer.setdefault(row.holder_id, []).append(row.seat_id)
        show_of_offer[row.holder_id] = row.show_id

    handled = 0
    for offer_id, seat_ids in by_offer.items():
        marked = (
            await session.execute(MARK_OFFER_EXPIRED, {"offer_id": offer_id})
        ).first()
        if marked is None:
            # Claimed in the interval between the timestamp passing and this
            # sweep. The claim wins; leave everything alone.
            logger.info("offer %s was claimed before the sweep; skipping", offer_id)
            continue

        await session.execute(DECLINE_ENTRY, {"entry_id": marked.entry_id})
        await assignment.assign_freed_seats(
            session, show_of_offer[offer_id], seat_ids
        )
        handled += 1

    await session.commit()
    if handled:
        logger.info("swept %d lapsed offer(s)", handled)
    return handled


async def sweep_orphaned_offers(session: AsyncSession) -> int:
    """Sweep 3: pending offers past their deadline with no live claims.

    Sweep 2 is driven by claim rows, so an offer whose claims vanished -- a
    crash between the claims expiring and the offer being marked -- would sit
    'pending' forever. This closes the window in which offer state and claim
    state can disagree.
    """
    offer_ids = (
        (await session.execute(ORPHANED_OFFERS, {"batch": BATCH})).scalars().all()
    )
    handled = 0
    for offer_id in offer_ids:
        marked = (
            await session.execute(MARK_OFFER_EXPIRED, {"offer_id": offer_id})
        ).first()
        if marked is None:
            continue
        await session.execute(DECLINE_ENTRY, {"entry_id": marked.entry_id})

        released = (
            await session.execute(RELEASE_OFFER_CLAIMS, {"offer_id": offer_id})
        ).all()
        show_id = await session.scalar(
            SHOW_OF_ENTRY, {"entry_id": marked.entry_id}
        )
        seat_ids = [r.seat_id for r in released] or list(marked.seat_ids or [])
        if show_id is not None and seat_ids:
            await assignment.assign_freed_seats(session, show_id, seat_ids)
        handled += 1

    await session.commit()
    if handled:
        logger.info("swept %d orphaned offer(s)", handled)
    return handled


async def run_tick() -> dict[str, int]:
    """One scheduler tick: three sweeps, each in its own transaction.

    A failure in one sweep must not stop the others, now or on the next tick,
    so each is caught and logged rather than allowed to kill the job.
    """
    results: dict[str, int] = {}
    for name, sweep in (
        ("expired_holds", sweep_expired_holds),
        ("lapsed_offers", sweep_lapsed_offers),
        ("orphaned_offers", sweep_orphaned_offers),
    ):
        try:
            async with SessionFactory() as session:
                results[name] = await sweep(session)
        except Exception:
            logger.exception("sweep %s failed; continuing", name)
            results[name] = -1

    global last_run_at
    last_run_at = datetime.now(timezone.utc)
    return results
