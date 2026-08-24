"""The read-only functions the model is allowed to call.

THE ARCHITECTURAL CONSTRAINT, IN CODE
Nothing in this module writes. There is no session.commit(), no INSERT, no
UPDATE, and no import of the hold, confirm, cancel, waitlist-join or
offer-claim services. The model resolves language into a structured filter,
these functions answer from the database, and the customer taps an option to
enter the ordinary booking flow. That flow is untouched.

The reason is not tidiness. A model that can book can book the wrong thing,
and no amount of prompting makes that safe -- so the capability is absent
rather than discouraged. Adding a write here would defeat the whole design.

AVAILABILITY IS DERIVED, NEVER CACHED
Every seat count below is computed with the same predicate the seat map uses:
a claim occupies a seat only while state IN ('held','booked') AND, for a
hold, expires_at > now(). A cached count would drift from the seat map within
seconds and the assistant would recommend seats that are gone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

#: Seats a claim occupies. Kept as one string so every query below shares it
#: with the seat map rather than re-deriving the rule.
_OCCUPIED = (
    "c.state = 'booked' OR (c.state = 'held' AND c.expires_at > now())"
)


def _decimal(value: Any) -> Decimal | None:
    """Money is Decimal end to end. Never float, not even briefly."""
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Any) -> str | None:
    """Serialised for the model as a string, so no float can sneak in."""
    amount = _decimal(value)
    return None if amount is None else f"{amount:.2f}"


# ---------------------------------------------------------------- 1. shows


FIND_SHOWS = text(
    f"""
    WITH avail AS (
        SELECT sh.id AS show_id,
               s.category_id,
               count(*) FILTER (WHERE c.id IS NULL OR NOT ({_OCCUPIED}))
                   AS available
          FROM show sh
          JOIN seat s ON s.screen_id = sh.screen_id AND s.is_active
          LEFT JOIN seat_claim c
            ON c.seat_id = s.id AND c.show_id = sh.id
           AND c.state IN ('held','booked')
         GROUP BY sh.id, s.category_id
    )
    SELECT sh.id                AS show_id,
           e.id                 AS event_id,
           e.title,
           e.event_type::text   AS event_type,
           e.genres,
           e.certification,
           e.runtime_min,
           v.name               AS venue_name,
           v.city,
           sc.name              AS screen_name,
           sh.starts_at,
           sh.language,
           sh.format::text      AS format,
           min(p.price)         AS from_price,
           sum(a.available)     AS seats_available,
           jsonb_agg(
               jsonb_build_object(
                   'category_id', cat.id,
                   'category', cat.name,
                   'price', p.price::text,
                   'available', a.available
               ) ORDER BY cat.rank
           )                    AS categories
      FROM show sh
      JOIN event e   ON e.id = sh.event_id
      JOIN screen sc ON sc.id = sh.screen_id
      JOIN venue v   ON v.id = sc.venue_id
      JOIN show_category_price p ON p.show_id = sh.id
      JOIN seat_category cat     ON cat.id = p.category_id
      JOIN avail a   ON a.show_id = sh.id AND a.category_id = cat.id
     WHERE sh.status = 'scheduled'
       AND sh.starts_at > now()
       AND sh.starts_at >= CAST(:date_from AS timestamptz)
       AND sh.starts_at < CAST(:date_to AS timestamptz)
       AND (CAST(:query AS text) IS NULL OR e.title ILIKE '%' || CAST(:query AS text) || '%')
       -- Overlap, not containment: a show matches if it shares AT LEAST ONE
       -- genre with what was asked for. Compared case-insensitively because
       -- the model retypes these from get_user_context and its casing drifts.
       AND (CAST(:genres AS text[]) IS NULL
            OR EXISTS (
                SELECT 1 FROM unnest(e.genres) AS g
                 WHERE lower(g) = ANY (
                     SELECT lower(w) FROM unnest(CAST(:genres AS text[])) AS w
                 )
            ))
       AND (CAST(:city AS text) IS NULL OR v.city ILIKE CAST(:city AS text))
       AND (CAST(:event_type AS text) IS NULL OR e.event_type::text = CAST(:event_type AS text))
       AND (CAST(:language AS text) IS NULL OR sh.language ILIKE CAST(:language AS text))
       AND (CAST(:format AS text) IS NULL OR sh.format::text = CAST(:format AS text))
     GROUP BY sh.id, e.id, e.title, e.event_type, e.genres, e.certification,
              e.runtime_min, v.name, v.city, sc.name, sh.starts_at,
              sh.language, sh.format
    HAVING sum(a.available) >= CAST(:min_seats AS integer)
       AND (CAST(:max_price AS numeric) IS NULL OR min(p.price) <= CAST(:max_price AS numeric))
     ORDER BY sh.starts_at
     LIMIT 25
    """
)


async def find_shows(
    session: AsyncSession,
    *,
    query: str | None = None,
    city: str | None = None,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    language: str | None = None,
    format: str | None = None,
    genres: list[str] | None = None,
    max_price: Decimal | str | float | None = None,
    min_seats_available: int = 1,
) -> list[dict[str, Any]]:
    """Shows matching a structured filter, cheapest price and seats attached.

    Defaults to the next seven days. `starts_at > now()` is in the WHERE
    clause as well as the date window: a show earlier today has already
    started and cannot be booked, so recommending it would waste a tap.

    `query` and `genres` are different axes and are easy to conflate: `query`
    is a title search, `genres` matches the event's genre tags. Without the
    second one, a model handed top_genres by get_user_context has nowhere to
    put them except `query` -- where "Sci-Fi Thriller Comedy" is read as a
    title, matches nothing, and personalisation fails silently.
    """
    # A model that has been asked for a list sometimes sends a bare string.
    if isinstance(genres, str):
        genres = [genres]
    wanted_genres = [g for g in (genres or []) if str(g).strip()] or None
    start = datetime.combine(
        date_from or date.today(), datetime.min.time(), tzinfo=timezone.utc
    )
    end = datetime.combine(
        date_to or (date.today() + timedelta(days=7)),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ) + timedelta(days=1)

    rows = (
        await session.execute(
            FIND_SHOWS,
            {
                "query": query or None,
                "city": city or None,
                "event_type": event_type or None,
                "language": language or None,
                "format": format or None,
                "genres": wanted_genres,
                "date_from": start,
                "date_to": end,
                "max_price": _decimal(max_price),
                "min_seats": max(1, int(min_seats_available or 1)),
            },
        )
    ).mappings().all()

    return [
        {
            "show_id": row["show_id"],
            "event_id": row["event_id"],
            "title": row["title"],
            "event_type": row["event_type"],
            "genres": list(row["genres"] or []),
            "certification": row["certification"],
            "runtime_min": row["runtime_min"],
            "venue": row["venue_name"],
            "city": row["city"],
            "screen": row["screen_name"],
            "starts_at": row["starts_at"].isoformat(),
            "language": row["language"],
            "format": row["format"],
            "from_price": _money(row["from_price"]),
            "seats_available": int(row["seats_available"]),
            "categories": row["categories"],
        }
        for row in rows
    ]


# --------------------------------------------------------- 2. availability


SHOW_AVAILABILITY = text(
    f"""
    SELECT cat.id            AS category_id,
           cat.name,
           cat.rank,
           p.price,
           count(s.id)                                          AS total_seats,
           count(*) FILTER (WHERE c.id IS NULL OR NOT ({_OCCUPIED}))
                                                                AS available,
           (SELECT count(*) FROM waitlist_entry w
             WHERE w.show_id = :show_id AND w.category_id = cat.id
               AND w.state IN ('waiting','offered'))            AS waitlist_size
      FROM show sh
      JOIN seat s   ON s.screen_id = sh.screen_id AND s.is_active
      JOIN seat_category cat ON cat.id = s.category_id
      JOIN show_category_price p
        ON p.show_id = sh.id AND p.category_id = cat.id
      LEFT JOIN seat_claim c
        ON c.seat_id = s.id AND c.show_id = sh.id
       AND c.state IN ('held','booked')
     WHERE sh.id = :show_id
     GROUP BY cat.id, cat.name, cat.rank, p.price
     ORDER BY cat.rank
    """
)

SHOW_SUMMARY = text(
    """
    SELECT e.title, v.name AS venue, sc.name AS screen, sh.starts_at,
           sh.language, sh.format::text AS format
      FROM show sh
      JOIN event e   ON e.id = sh.event_id
      JOIN screen sc ON sc.id = sh.screen_id
      JOIN venue v   ON v.id = sc.venue_id
     WHERE sh.id = :show_id
    """
)


async def get_show_availability(
    session: AsyncSession, *, show_id: int
) -> dict[str, Any]:
    """Per-category availability for one show."""
    summary = (
        await session.execute(SHOW_SUMMARY, {"show_id": show_id})
    ).mappings().first()
    if summary is None:
        return {"error": "no_such_show", "show_id": show_id}

    rows = (
        await session.execute(SHOW_AVAILABILITY, {"show_id": show_id})
    ).mappings().all()

    return {
        "show_id": show_id,
        "title": summary["title"],
        "venue": summary["venue"],
        "screen": summary["screen"],
        "starts_at": summary["starts_at"].isoformat(),
        "language": summary["language"],
        "format": summary["format"],
        "categories": [
            {
                "category_id": row["category_id"],
                "name": row["name"],
                "price": _money(row["price"]),
                "total_seats": int(row["total_seats"]),
                "available": int(row["available"]),
                "sold_out": int(row["available"]) == 0,
                # Only meaningful on a sold-out category, but reported either
                # way so the model never has to infer it.
                "waitlist_size": int(row["waitlist_size"]),
                "waitlist_available": int(row["available"]) == 0,
            }
            for row in rows
        ],
    }


# ------------------------------------------------------------ 3. seat rank


AVAILABLE_SEATS = text(
    f"""
    SELECT s.id, s.row_label, s.seat_number, s.x, s.y,
           s.category_id, cat.name AS category, cat.rank AS category_rank,
           p.price
      FROM show sh
      JOIN seat s   ON s.screen_id = sh.screen_id AND s.is_active
      JOIN seat_category cat ON cat.id = s.category_id
      JOIN show_category_price p
        ON p.show_id = sh.id AND p.category_id = cat.id
      LEFT JOIN seat_claim c
        ON c.seat_id = s.id AND c.show_id = sh.id
       AND c.state IN ('held','booked')
     WHERE sh.id = :show_id
       AND (c.id IS NULL OR NOT ({_OCCUPIED}))
       AND (CAST(:category_id AS bigint) IS NULL OR s.category_id = CAST(:category_id AS bigint))
     ORDER BY s.y, s.x
    """
)

#: The band of the hall people actually prefer, as a fraction of depth from
#: the screen. Front rows crane the neck; the back loses the screen. Roughly
#: 55-65% back is the accepted sweet spot, so the score peaks at 0.6.
_OPTIMAL_DEPTH = 0.60


async def rank_seats(
    session: AsyncSession,
    *,
    show_id: int,
    qty: int,
    max_total: Decimal | str | float | None = None,
    category_id: int | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """Up to five candidate seat groups, with the score broken out.

    ADJACENCY IS A HARD REQUIREMENT, not a scoring term. A group is only ever
    formed from seats that are consecutive by x within a single row, so a
    party of three is never offered three seats scattered across the hall.
    Because x carries the layout's aisle offsets, "consecutive by x" also
    means nobody is asked to sit across an aisle from their own party.

    Everything else is a weighted score, and every component is returned.
    The assistant can then say WHY a group is good using numbers it was
    given, instead of inventing a reason that sounds plausible.
    """
    qty = max(1, min(int(qty), settings.max_seats_per_hold))

    rows = (
        await session.execute(
            AVAILABLE_SEATS, {"show_id": show_id, "category_id": category_id}
        )
    ).mappings().all()

    if not rows:
        return {"show_id": show_id, "qty": qty, "groups": [], "reason": "no_seats"}

    budget = _decimal(max_total)

    # Geometry of the whole hall, for centrality and depth.
    xs = [r["x"] for r in rows]
    ys = [r["y"] for r in rows]
    min_y, max_y = min(ys), max(ys)
    depth_span = max(1, max_y - min_y)

    by_row: dict[int, list[dict]] = {}
    for row in rows:
        by_row.setdefault(row["y"], []).append(dict(row))

    candidates: list[dict[str, Any]] = []

    for y, seats in by_row.items():
        seats.sort(key=lambda s: s["x"])
        row_min_x = min(s["x"] for s in seats)
        row_max_x = max(s["x"] for s in seats)
        row_centre = (row_min_x + row_max_x) / 2
        row_half = max(1.0, (row_max_x - row_min_x) / 2)

        # Every window of `qty` consecutive seats in this row.
        for start in range(len(seats) - qty + 1):
            window = seats[start : start + qty]

            # HARD: contiguous by x, no gap, no aisle inside the party.
            contiguous = all(
                window[i + 1]["x"] - window[i]["x"] == 1 for i in range(qty - 1)
            )
            if not contiguous:
                continue
            # HARD: one category per group, so the price is unambiguous.
            if len({s["category_id"] for s in window}) != 1:
                continue

            price = _decimal(window[0]["price"]) or Decimal("0")
            total = price * qty
            if budget is not None and total > budget:
                continue

            centre = sum(s["x"] for s in window) / qty
            # 1.0 dead centre, 0.0 at the far edge of the row.
            centrality = max(0.0, 1.0 - abs(centre - row_centre) / row_half)

            depth = (y - min_y) / depth_span
            # 1.0 at the optimal band, falling off either side.
            depth_score = max(0.0, 1.0 - abs(depth - _OPTIMAL_DEPTH) / 0.6)

            # Cheaper is better WITHIN budget; neutral when no budget given.
            budget_fit = (
                1.0 if budget is None or budget == 0
                else float(1 - (total / budget))
            )
            # Better categories rank lower (1 = best).
            category_score = 1.0 / float(window[0]["category_rank"] or 1)

            aisle = window[0]["x"] == row_min_x or window[-1]["x"] == row_max_x

            weights = {
                "central": (0.45, 0.30, 0.10, 0.15),
                "front": (0.20, 0.10, 0.15, 0.15),
                "back": (0.20, 0.10, 0.15, 0.15),
                "aisle": (0.20, 0.20, 0.15, 0.15),
                None: (0.35, 0.25, 0.20, 0.20),
            }
            w_centre, w_depth, w_budget, w_cat = weights.get(
                prefer, weights[None]
            )

            score = (
                w_centre * centrality
                + w_depth * depth_score
                + w_budget * max(0.0, budget_fit)
                + w_cat * category_score
            )
            # Explicit preferences add their own term rather than replacing
            # the base score, so a front-row request still prefers the better
            # of two front rows.
            if prefer == "front":
                score += 0.40 * (1.0 - depth)
            elif prefer == "back":
                score += 0.40 * depth
            elif prefer == "aisle":
                score += 0.40 * (1.0 if aisle else 0.0)

            candidates.append(
                {
                    "seat_ids": [s["id"] for s in window],
                    "seats": [f"{s['row_label']}{s['seat_number']}" for s in window],
                    "row": window[0]["row_label"],
                    "category_id": window[0]["category_id"],
                    "category": window[0]["category"],
                    "price_per_seat": _money(price),
                    "total": _money(total),
                    "score": round(score, 4),
                    "score_breakdown": {
                        "adjacency": "contiguous in row "
                        f"{window[0]['row_label']}",
                        "centrality": round(centrality, 3),
                        "depth": round(depth_score, 3),
                        "depth_fraction": round(depth, 3),
                        "budget_fit": round(max(0.0, budget_fit), 3),
                        "category_rank": window[0]["category_rank"],
                        "on_aisle": aisle,
                    },
                }
            )

    # Deterministic: score desc, then a stable tiebreak on the seat ids, so
    # the same request always produces the same answer in the same order.
    candidates.sort(key=lambda c: (-c["score"], c["seat_ids"]))

    # One group per row, so five options are five real choices rather than
    # the same block shifted one seat sideways.
    seen_rows: set[str] = set()
    groups: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["row"] in seen_rows:
            continue
        seen_rows.add(candidate["row"])
        groups.append(candidate)
        if len(groups) == 5:
            break

    return {
        "show_id": show_id,
        "qty": qty,
        "max_total": _money(budget),
        "prefer": prefer,
        "groups": groups,
        "reason": None if groups else "no_adjacent_group_within_constraints",
    }


# --------------------------------------------------------- 4. user context


USER_CONTEXT = text(
    """
    SELECT b.reference,
           b.total_amount,
           b.created_at,
           sh.starts_at,
           v.name          AS venue,
           e.genres,
           cat.name        AS category,
           count(bs.seat_id) AS party_size
      FROM booking b
      JOIN show sh   ON sh.id = b.show_id
      JOIN event e   ON e.id = sh.event_id
      JOIN screen sc ON sc.id = sh.screen_id
      JOIN venue v   ON v.id = sc.venue_id
      JOIN booking_seat bs ON bs.booking_id = b.id
      JOIN seat_category cat ON cat.id = bs.category_id
     WHERE b.user_id = :user_id AND b.status = 'confirmed'
     GROUP BY b.id, b.reference, b.total_amount, b.created_at,
              sh.starts_at, v.name, e.genres, cat.name
     ORDER BY sh.starts_at DESC
     LIMIT 100
    """
)


def _mode(values: list[Any]) -> Any | None:
    if not values:
        return None
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts.items(), key=lambda item: (item[1], str(item[0])))[0]


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


async def get_user_context(
    session: AsyncSession, *, user_id: int
) -> dict[str, Any]:
    """Habits derived from this user's own confirmed bookings.

    Returns `has_history: false` and nothing else for a new account. Guessing
    a preference for someone with no bookings would make the assistant sound
    confident about a person it has never seen, and the recommendation would
    be indistinguishable from an invented one.

    SECURITY: the caller passes user_id from the verified JWT. The model
    cannot name a user -- the tool schema has no user_id parameter at all, so
    there is no field for it to fill in. See service.py.
    """
    rows = (
        await session.execute(USER_CONTEXT, {"user_id": user_id})
    ).mappings().all()

    if not rows:
        return {"has_history": False, "bookings": 0}

    party_sizes = [int(r["party_size"]) for r in rows]
    hours = [r["starts_at"].astimezone(timezone.utc).hour for r in rows]
    totals = [_decimal(r["total_amount"]) or Decimal("0") for r in rows]
    per_seat = [
        (total / size) for total, size in zip(totals, party_sizes) if size
    ]

    genres: list[str] = []
    for row in rows:
        genres.extend(row["genres"] or [])

    typical_hour = _mode(hours)

    return {
        "has_history": True,
        "bookings": len(rows),
        "usual_party_size": _mode(party_sizes),
        # A band rather than an hour: "you usually book evenings" is true;
        # "you usually book at 19:00" is over-claiming from a handful of rows.
        "typical_showtime_band": (
            None
            if typical_hour is None
            else "morning"
            if typical_hour < 12
            else "afternoon"
            if typical_hour < 17
            else "evening"
        ),
        "most_booked_category": _mode([r["category"] for r in rows]),
        "median_spend_per_seat": _money(_median(per_seat)),
        "most_visited_venue": _mode([r["venue"] for r in rows]),
        "top_genres": [
            genre
            for genre, _ in sorted(
                {g: genres.count(g) for g in set(genres)}.items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        ],
    }
