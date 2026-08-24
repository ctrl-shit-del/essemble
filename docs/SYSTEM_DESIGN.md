# ESSEMBLE — System Design

Covers seat hold and TTL, concurrency prevention, waitlist auto-assignment, and time-limited offer handling.

## Foundation: one table, derived status

There is no `status` column on `seat`. All seat state for a show lives in a single `seat_claim` table, and status is derived at read time:

```
booked     → active claim, state='booked'
held       → active claim, state='held' AND expires_at > now()
available  → anything else
```

A stored status requires dual writes and drifts under partial failure. A derived status cannot. Every mechanism below follows from this.

## 1. Seat hold and TTL

A hold is a row in `seat_claim` with `state='held'` and an `expires_at` timestamp set to `now() + HOLD_TTL_SECONDS` (default 600).

Expiry is enforced in two layers, and the authoritative one is not the scheduler.

**Lazy expiry is the truth.** Every read filters on `expires_at > now()`, and every acquisition can take over an already-expired claim in the same atomic statement. A hold is therefore functionally released the instant its timestamp passes, whether or not any background process is running.

**The sweeper materialises side effects only.** Every ten seconds it transitions expired rows to `state='expired'`, bumps the show's `seat_version`, emits the realtime event, and triggers the waitlist cascade:

```sql
UPDATE seat_claim SET state='expired'
WHERE id IN (
  SELECT id FROM seat_claim
  WHERE state='held' AND expires_at <= now()
  ORDER BY expires_at LIMIT 200
  FOR UPDATE SKIP LOCKED
) RETURNING show_id, seat_id;
```

`SKIP LOCKED` allows parallel workers without collision.

This layering is deliberate: the app is hosted on a free tier that sleeps. A scheduler-only design would silently stop releasing seats while asleep. Here, sleeping only delays the UI notification — correctness never depends on the worker.

## 2. Concurrency prevention

The guarantee is a database constraint, not application discipline:

```sql
CREATE UNIQUE INDEX one_active_claim
  ON seat_claim (show_id, seat_id)
  WHERE state IN ('held','booked');
```

Acquisition is one statement per seat. There is no availability read beforehand — no check-then-insert anywhere in the path:

```sql
INSERT INTO seat_claim (...) VALUES (...)
ON CONFLICT (show_id, seat_id) WHERE state IN ('held','booked')
DO UPDATE SET holder_id=EXCLUDED.holder_id, ...
WHERE seat_claim.state='held' AND seat_claim.expires_at <= now()
RETURNING id;
```

A returned row means the seat was won. Zero rows means it is live-held or booked, and the entire transaction aborts — multi-seat holds are all-or-nothing, with seats processed in ascending `seat_id` order to avoid deadlocks under crossed requests.

The `DO UPDATE` arm atomically takes over a hold that has expired but not yet been swept, so expiry and acquisition resolve in a single statement with no race window.

Because the guarantee is an index, it holds across restarts, across instances, and regardless of code path. Confirmation uses the same shape: an `UPDATE ... WHERE state='held' AND expires_at > now()` whose row count is the entire guard, with no preceding read.

`scripts/concurrency_test.py` proves this over HTTP: fifty simultaneous holds on one seat yield exactly one success, and overlapping multi-seat requests leave no partial holds behind.

## 3. Waitlist auto-assignment

Waitlist entries are per seat category. Position is computed from `created_at` at read time, never stored, so a cancellation never forces renumbering.

Cancellation is one transaction: the booking is cancelled, its claims released, freed seats grouped by category, and per category the oldest `waiting` entry whose quantity fits is selected `FOR UPDATE SKIP LOCKED`, so concurrent cancellations cannot offer the same entry. An entry too large for the freed count is skipped rather than blocking the queue.

Critically, those seats are **immediately re-claimed** in the same transaction with `holder_type='waitlist_offer'`, using the identical `INSERT ... ON CONFLICT` statement — so an offered seat is never bookable by a browsing customer, and the offer inherits the concurrency guarantee for free. Splitting offer creation from re-claim would open a window where promised seats read as available. They are not split.

## 4. Time-limited offer handling

The offer email carries a random 32-byte token; only its SHA-256 hash is stored. Claiming is a guarded update:

```sql
UPDATE waitlist_offer SET state='claimed'
WHERE id=:id AND state='pending' AND expires_at > now();
```

A row count of one is a valid claim; anything else returns the same `OFFER_EXPIRED` response whether the offer lapsed or was already used — single use enforced in one place, leaking nothing.

Offer expiry rides the same sweeper as hold expiry. When an offer's claims lapse, the offer is marked expired, the entry declined, and the seats cascade to the next fitting entry — or return to available if the queue is empty. A third sweep catches offers still `pending` whose claims are gone, closing the window where offer state and claim state could disagree.

Both TTL systems are one mechanism, one table, one worker.