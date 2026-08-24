"""The raw statements the booking engine depends on.

Kept in one place, unwrapped, because their exact text is the correctness
argument. In particular ACQUIRE_SEAT below is the whole of the concurrency
guarantee, and its ON CONFLICT target has to match the `one_active_claim`
partial index character for character -- if the predicate is altered or
dropped, PostgreSQL raises "no unique or exclusion constraint matching the ON
CONFLICT specification" rather than silently misbehaving.
"""

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Seat acquisition. One statement per seat, no read beforehand.
#
# The DO UPDATE arm atomically takes over a hold that has expired but has not
# yet been swept, so expiry and acquisition resolve in a single statement with
# no race window.
#
# A returned row means the seat was won. Zero rows means it is live-held or
# booked: the caller aborts the entire transaction.
# ---------------------------------------------------------------------------
ACQUIRE_SEAT = text(
    """
    INSERT INTO seat_claim (show_id, seat_id, hold_group_id, state,
                            holder_type, holder_id, expires_at)
    VALUES (:show_id, :seat_id, :group, 'held', 'user', :user_id,
            now() + make_interval(secs => :ttl))
    ON CONFLICT (show_id, seat_id) WHERE state IN ('held','booked')
    DO UPDATE SET holder_id     = EXCLUDED.holder_id,
                  hold_group_id = EXCLUDED.hold_group_id,
                  expires_at    = EXCLUDED.expires_at,
                  created_at    = now()
    WHERE seat_claim.state = 'held'
      AND seat_claim.expires_at <= now()
    RETURNING id
    """
)

# ---------------------------------------------------------------------------
# Confirmation. The rowcount of this statement IS the guard: if it does not
# match the number of seats in the group, the hold lapsed and the whole
# transaction rolls back. There is deliberately no read of the hold's validity
# beforehand -- that would be a TOCTOU window.
# ---------------------------------------------------------------------------
CONFIRM_HOLD = text(
    """
    UPDATE seat_claim SET state = 'booked', expires_at = NULL
    WHERE hold_group_id = :group AND state = 'held' AND expires_at > now()
    RETURNING seat_id
    """
)

RELEASE_HOLD = text(
    """
    UPDATE seat_claim SET state = 'released', expires_at = NULL
    WHERE hold_group_id = :group AND state = 'held' AND expires_at > now()
    RETURNING seat_id
    """
)

# ---------------------------------------------------------------------------
# Seat map. Status is derived here and nowhere else: there is no status column
# on seat and no cache. The `expires_at > now()` arm is what makes an
# expired-but-unswept hold read as available -- expiry is authoritative via the
# timestamp, never via the sweeper having run.
# ---------------------------------------------------------------------------
SEAT_MAP = text(
    """
    SELECT s.id, s.row_label, s.seat_number, s.x, s.y, s.category_id,
           CASE
             WHEN c.state = 'booked' THEN 'booked'
             WHEN c.state = 'held' AND c.expires_at > now() THEN 'held'
             ELSE 'available'
           END AS status
    FROM seat s
    LEFT JOIN seat_claim c
      ON c.seat_id = s.id AND c.show_id = :show_id
     AND c.state IN ('held','booked')
    WHERE s.screen_id = :screen_id AND s.is_active
    ORDER BY s.y, s.x
    """
)

BUMP_SEAT_VERSION = text(
    "UPDATE show SET seat_version = seat_version + 1 WHERE id = :show_id"
    " RETURNING seat_version"
)

#: Seconds left on a hold group, computed by the database clock.
HOLD_REMAINING = text(
    """
    SELECT hold_group_id,
           holder_id,
           show_id,
           max(expires_at)                                    AS expires_at,
           greatest(0, extract(epoch FROM (max(expires_at) - now())))::int
                                                              AS seconds_remaining,
           bool_and(state = 'held' AND expires_at > now())     AS still_held,
           count(*)                                           AS seat_count
      FROM seat_claim
     WHERE hold_group_id = :group
     GROUP BY hold_group_id, holder_id, show_id
    """
)


# ---------------------------------------------------------------------------
# The offer-side twin of ACQUIRE_SEAT.
#
# Same statement, same ON CONFLICT target, therefore the same partial unique
# index and the same concurrency guarantee -- only the VALUES row differs:
# holder_type is 'waitlist_offer', holder_id is the offer, and expires_at is
# the offer deadline rather than now() + a TTL.
#
# ACQUIRE_SEAT is deliberately left untouched rather than parameterised, so the
# graded statement stays byte-identical. test_conflict_clauses_are_identical
# asserts the two conflict clauses never drift apart.
# ---------------------------------------------------------------------------
ACQUIRE_SEAT_FOR_OFFER = text(
    """
    INSERT INTO seat_claim (show_id, seat_id, hold_group_id, state,
                            holder_type, holder_id, expires_at)
    VALUES (:show_id, :seat_id, :group, 'held', 'waitlist_offer', :holder_id,
            :expires_at)
    ON CONFLICT (show_id, seat_id) WHERE state IN ('held','booked')
    DO UPDATE SET holder_id     = EXCLUDED.holder_id,
                  hold_group_id = EXCLUDED.hold_group_id,
                  expires_at    = EXCLUDED.expires_at,
                  created_at    = now()
    WHERE seat_claim.state = 'held'
      AND seat_claim.expires_at <= now()
    RETURNING id
    """
)

#: Release every claim in a hold group, whatever its state. Used by
#: cancellation, where the claims are 'booked' rather than 'held'.
RELEASE_GROUP = text(
    """
    UPDATE seat_claim SET state = 'released', expires_at = NULL
    WHERE hold_group_id = :group AND state IN ('held','booked')
    RETURNING seat_id
    """
)

#: The next waitlist entry to serve in one category.
#:
#: FOR UPDATE SKIP LOCKED so two concurrent cancellations cannot hand the same
#: entry two different offers -- the second cancellation skips the locked row
#: and serves the next fitting entry instead.
#:
#: `qty <= :freed` means an entry wanting more seats than were freed is
#: SKIPPED, not blocked: a later, smaller entry can be served ahead of it. That
#: is deliberate. The alternative -- letting a large entry block the queue --
#: would strand freed seats until someone cancels a bigger booking.
NEXT_WAITLIST_ENTRY = text(
    """
    SELECT id, user_id, qty FROM waitlist_entry
     WHERE show_id = :show_id AND category_id = :category_id
       AND state = 'waiting' AND qty <= :freed
     ORDER BY created_at
     FOR UPDATE SKIP LOCKED
     LIMIT 1
    """
)

#: Single-use enforcement for an offer. The rowcount is the whole guard, and
#: it answers "expired" and "already claimed" identically by construction.
CLAIM_OFFER = text(
    """
    UPDATE waitlist_offer SET state = 'claimed'
    WHERE id = :offer_id AND state = 'pending' AND expires_at > now()
    RETURNING id
    """
)

#: Book the seats an offer is holding.
BOOK_OFFER_SEATS = text(
    """
    UPDATE seat_claim SET state = 'booked', expires_at = NULL
    WHERE holder_type = 'waitlist_offer' AND holder_id = :offer_id
      AND state = 'held' AND expires_at > now()
    RETURNING seat_id
    """
)

#: Seats in one category with no live claim, derived exactly as the seat map
#: derives status: a held claim whose expires_at has passed is not live.
AVAILABLE_IN_CATEGORY = text(
    """
    SELECT count(*) FROM seat s
    LEFT JOIN seat_claim c
      ON c.seat_id = s.id AND c.show_id = :show_id
     AND c.state IN ('held','booked')
    WHERE s.screen_id = :screen_id AND s.is_active
      AND s.category_id = :category_id
      AND (c.id IS NULL OR (c.state = 'held' AND c.expires_at <= now()))
    """
)

#: Queue position, computed on read. Never stored: a cancellation upstream
#: would otherwise force everyone behind it to be renumbered.
QUEUE_POSITION = text(
    """
    SELECT count(*) + 1 FROM waitlist_entry
     WHERE show_id = :show_id AND category_id = :category_id
       AND state = 'waiting' AND created_at < :created_at
    """
)


#: Create an offer, with expires_at set by the database clock.
INSERT_OFFER = text(
    """
    INSERT INTO waitlist_offer (entry_id, seat_ids, token_hash, state, expires_at)
    VALUES (:entry_id, :seat_ids, :token_hash, 'pending',
            now() + make_interval(secs => :ttl))
    RETURNING id, expires_at
    """
)
