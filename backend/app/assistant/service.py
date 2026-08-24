"""Orchestration: the server-side tool-use loop.

The loop is deliberately ordinary -- send, check stop_reason, execute the
requested tools, send the results back, repeat -- because the interesting
constraint is not in the loop but in what the tools can do. See tools.py.

The one thing this file guards jealously is WHO the request is for. The
authenticated user's id comes from the JWT and is injected into
get_user_context here; the tool schema the model sees has no user_id field,
so there is no parameter for it to fill in with someone else's.

The provider is Groq, reached through the `openai` SDK because Groq speaks
the OpenAI wire protocol. Everything provider-shaped lives in `_complete`
below; the rest of the file would not notice a swap.

Running on Llama rather than Claude changes the risk profile of the loop, not
its structure. A smaller model emits malformed tool arguments more often and
is likelier to invent an id, so two guards exist here that a stronger model
would rarely exercise: `_run_tool` refuses to crash on unparseable arguments,
and `_verify_options` drops any option whose ids did not come out of a tool
result in this very conversation. The system prompt forbids inventing them;
these enforce it, and enforcement beats instruction when the model is weaker.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import openai
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import tools
from app.assistant.prompts import SYSTEM_PROMPT
from app.assistant.schemas import (
    ChatRequest,
    ChatResponse,
    SeatOption,
    ShowOption,
)
from app.core.config import settings
from app.core.errors import AppError, ErrorCode

logger = logging.getLogger("essemble.assistant")


#: The timezone the catalogue is authored in. Showtimes are stored as UTC
#: timestamptz but written as Indian local time, so "tonight" only lands on
#: the right rows when it is resolved here. A fixed offset rather than a
#: zoneinfo lookup: India has no DST, so the offset is exact, and this avoids
#: depending on a tz database being installed -- which on Windows is an extra
#: package that would be a silent, dated-by-one-day failure if missing.
IST = timezone(timedelta(hours=5, minutes=30))


def _today_message() -> dict[str, Any]:
    """Tell the model what day it is.

    Without this it guesses, and it guesses wrong: asked for "anything on
    tonight" it resolved the window to YESTERDAY and then reported,
    confidently, that nothing was on. The system prompt tells it to turn
    "tonight" and "this weekend" into concrete dates; nothing was telling it
    what to count from.

    A SEPARATE system message rather than a line inside SYSTEM_PROMPT: the
    prompt is a stable cache prefix and this content changes every minute, so
    folding it in would invalidate that prefix on every single request.
    """
    now = datetime.now(IST)
    return {
        "role": "system",
        "content": (
            f"Today is {now.date().isoformat()} ({now.strftime('%A')}) in "
            f"India, and the current local time is {now.strftime('%H:%M')} "
            "IST (UTC+05:30). Resolve 'tonight', 'tomorrow' and 'this "
            "weekend' against that date. Tool results report starts_at as a "
            "UTC timestamp ending +00:00, which is 5 hours 30 minutes BEHIND "
            "the local time a customer recognises. If you are not confident "
            "converting it, name the show and let the card show the time "
            "rather than stating a time that might be wrong."
        ),
    }


#: What the loop says when the model's own tool call is unreadable. It is a
#: plain request to try again rather than an error page, because from the
#: customer's side nothing has gone wrong that rephrasing will not fix.
REPHRASE_REPLY = "I didn't catch that, can you rephrase?"


def assistant_available() -> bool:
    return bool(settings.groq_api_key)


def unavailable() -> AppError:
    return AppError(
        ErrorCode.INTERNAL_ERROR,
        "The booking assistant is not configured on this deployment.",
        503,
        {"reason": "missing_api_key"},
    )


# ------------------------------------------------------------- rate limit


#: user_id -> timestamps of recent messages. In-memory is the right size for
#: this: the limit exists to stop one account burning the API budget, not to
#: be a distributed quota, and a process restart resetting it is harmless.
_recent: dict[int, deque[float]] = defaultdict(deque)


def check_rate_limit(user_id: int) -> None:
    window = 3600.0
    now = time.monotonic()
    hits = _recent[user_id]
    while hits and now - hits[0] > window:
        hits.popleft()

    if len(hits) >= settings.assistant_rate_limit_per_hour:
        retry_after = int(window - (now - hits[0])) + 1
        raise AppError(
            ErrorCode.CONFLICT,
            "You have reached the assistant's hourly limit.",
            429,
            {"retry_after_seconds": retry_after},
        )
    hits.append(now)


def reset_rate_limits() -> None:
    """Test seam."""
    _recent.clear()


# ---------------------------------------------------------- tool schemas


#: What the model sees. Note there is NO user_id anywhere -- get_user_context
#: takes no parameters at all, precisely so the model cannot address a user
#: other than the caller.
#:
#: Declared in the plain name/description/parameters form and wrapped into the
#: provider's envelope below, so the envelope is the only thing that changes
#: if the provider does.
_FUNCTIONS: list[dict[str, Any]] = [
    {
        "name": "find_shows",
        "description": (
            "Search upcoming shows. Returns each show with its venue, "
            "showtime, cheapest category price, and seats available per "
            "category. Defaults to the next 7 days. Note that `query` "
            "searches TITLES and `genres` searches genre tags -- they are "
            "different filters and a genre put in `query` matches nothing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Free text matched against the event TITLE only. Do "
                        "not put genres here -- use the genres parameter."
                    ),
                },
                "genres": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Genre tags, e.g. [\"Sci-Fi\", \"Thriller\"]. A show "
                        "matches if it carries AT LEAST ONE of them. This is "
                        "where the top_genres from get_user_context belong."
                    ),
                },
                "city": {"type": "string"},
                "event_type": {"type": "string", "enum": ["movie", "live"]},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "language": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["2D", "3D", "IMAX", "EPIQ_3D"],
                },
                "max_price": {
                    "type": "string",
                    "description": (
                        "Decimal string. Cheapest category must be at or "
                        "below this."
                    ),
                },
                "min_seats_available": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_show_availability",
        "description": (
            "Per-category seats, prices, sold-out flags and waitlist size for "
            "one show."
        ),
        "parameters": {
            "type": "object",
            "properties": {"show_id": {"type": "integer"}},
            "required": ["show_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "rank_seats",
        "description": (
            "Up to 5 candidate seat groups for a party. Every group is "
            "contiguous within one row. Returns a score breakdown "
            "(adjacency, centrality, depth, budget fit, category) so you can "
            "explain the choice with real numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "show_id": {"type": "integer"},
                "qty": {"type": "integer", "minimum": 1},
                "max_total": {
                    "type": "string",
                    "description": "Decimal string, total for the whole party.",
                },
                "category_id": {"type": "integer"},
                "prefer": {
                    "type": "string",
                    "enum": ["central", "front", "back", "aisle"],
                },
            },
            "required": ["show_id", "qty"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_user_context",
        "description": (
            "Booking habits of the customer you are talking to: usual party "
            "size, typical showtime band, most-booked category, median spend, "
            "most-visited venue, top genres. Returns has_history=false for a "
            "new customer. Takes no arguments -- it always describes the "
            "current customer and cannot describe anyone else."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]

#: The OpenAI tool envelope, which Groq speaks verbatim.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": function} for function in _FUNCTIONS
]


# ------------------------------------------------------------ tool runner


class MalformedToolCall(Exception):
    """The model's own tool arguments could not be read.

    Not an application error: the request was fine and the database was fine,
    a weaker model simply emitted something that is not JSON. It surfaces to
    the customer as a request to rephrase, never as a 500.
    """


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Read `function.arguments`, which arrives as a JSON STRING.

    This is the first real difference from the Anthropic shape, where the
    arguments came back already parsed. Llama-class models truncate the
    string, emit a Python-ish literal, or wrap it in an apology often enough
    that parsing it defensively is the normal path rather than the edge.
    """
    # Some OpenAI-compatible providers pre-parse. Accept either.
    if isinstance(raw, dict):
        return raw
    # A no-argument tool legitimately sends "" or nothing at all.
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if not isinstance(raw, str):
        raise MalformedToolCall(
            f"arguments were {type(raw).__name__}, not a JSON string"
        )

    try:
        parsed = json.loads(raw)
    except ValueError as exc:  # JSONDecodeError is a subclass
        raise MalformedToolCall(str(exc)) from exc

    if not isinstance(parsed, dict):
        raise MalformedToolCall("arguments were not a JSON object")
    return parsed


async def _run_tool(
    session: AsyncSession, name: str, raw_input: Any, user_id: int
) -> Any:
    """Dispatch one tool call. Never raises into the loop."""
    # Callers hand this a parsed dict; anything else is a malformed call and
    # is treated as no arguments rather than trusted for its shape.
    payload: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}

    try:
        if name == "find_shows":
            from datetime import date as _date

            def as_date(value: Any) -> Any:
                if not value:
                    return None
                try:
                    return _date.fromisoformat(str(value))
                except ValueError:
                    return None

            return await tools.find_shows(
                session,
                query=payload.get("query"),
                city=payload.get("city"),
                event_type=payload.get("event_type"),
                date_from=as_date(payload.get("date_from")),
                date_to=as_date(payload.get("date_to")),
                language=payload.get("language"),
                format=payload.get("format"),
                genres=payload.get("genres"),
                max_price=payload.get("max_price"),
                min_seats_available=payload.get("min_seats_available") or 1,
            )

        if name == "get_show_availability":
            return await tools.get_show_availability(
                session, show_id=int(payload["show_id"])
            )

        if name == "rank_seats":
            return await tools.rank_seats(
                session,
                show_id=int(payload["show_id"]),
                qty=int(payload["qty"]),
                max_total=payload.get("max_total"),
                category_id=payload.get("category_id"),
                prefer=payload.get("prefer"),
            )

        if name == "get_user_context":
            # user_id comes from the JWT, NEVER from the model's arguments.
            # Anything the model put in `payload` is ignored entirely.
            return await tools.get_user_context(session, user_id=user_id)

        return {"error": f"unknown tool {name}"}

    except (KeyError, ValueError, TypeError) as exc:
        # A bad argument is data, not a crash: hand it back and let the model
        # correct itself on the next turn.
        logger.warning("assistant tool %s rejected input: %s", name, exc)
        return {"error": "invalid_arguments", "detail": str(exc)}


# --------------------------------------------------------------- options


def _reason_for(group: dict[str, Any], max_total: str | None) -> str:
    """A sentence built from the score, not from the model's imagination."""
    parts = [f"adjacent in row {group['row']}"]

    breakdown = group.get("score_breakdown", {})
    centrality = breakdown.get("centrality", 0)
    if centrality >= 0.8:
        parts.append("centre block")
    elif centrality >= 0.5:
        parts.append("near the middle")

    depth = breakdown.get("depth", 0)
    if depth >= 0.8:
        parts.append("ideal distance from the screen")

    if breakdown.get("on_aisle"):
        parts.append("on the aisle")

    if max_total:
        parts.append(f"₹{group['total']} of your ₹{max_total}")
    else:
        parts.append(f"₹{group['total']} total")

    return ", ".join(parts)


def _collect_options(
    tool_results: list[tuple[str, Any]],
) -> list[ShowOption | SeatOption]:
    """Turn tool output into typed options for the UI.

    Built from the TOOL RESULTS, not from the model's prose. The model
    decides what to say; the options are whatever the database actually
    returned, so the cards cannot disagree with reality even if the reply
    does.
    """
    options: list[ShowOption | SeatOption] = []
    seen_shows: set[int] = set()

    for name, result in tool_results:
        if name == "find_shows" and isinstance(result, list):
            for show in result[:6]:
                if show["show_id"] in seen_shows:
                    continue
                seen_shows.add(show["show_id"])
                options.append(
                    ShowOption(
                        show_id=show["show_id"],
                        title=show["title"],
                        venue=show["venue"],
                        city=show.get("city"),
                        screen=show["screen"],
                        starts_at=show["starts_at"],
                        language=show["language"],
                        format=show.get("format"),
                        from_price=show.get("from_price"),
                        seats_available=show["seats_available"],
                    )
                )

        elif name == "rank_seats" and isinstance(result, dict):
            max_total = result.get("max_total")
            for group in result.get("groups", []):
                options.append(
                    SeatOption(
                        show_id=result["show_id"],
                        seat_ids=group["seat_ids"],
                        seats=group["seats"],
                        row=group["row"],
                        category=group["category"],
                        category_id=group["category_id"],
                        price_per_seat=group["price_per_seat"],
                        total=group["total"],
                        reason=_reason_for(group, max_total),
                        score_breakdown=group["score_breakdown"],
                    )
                )

    # Seat options are a more specific answer than show options, so when both
    # are present the seats lead.
    options.sort(key=lambda option: 0 if option.kind == "seats" else 1)
    return options


# ------------------------------------------------- hallucination guard


def _ledger(tool_results: list[tuple[str, Any]]) -> tuple[set[int], set[int]]:
    """Every show id and seat id this conversation actually saw from the DB.

    Only ids that arrived in a tool RESULT count. An id the model merely
    passed as an argument does not -- that is exactly the number a model
    invents, and echoing it back would launder a guess into a fact.

    `rank_seats` returns the show_id it was asked about, so it only earns a
    place here when it also returned at least one group: the groups are rows
    the database matched for that show, which is what proves the show real.
    """
    shows: set[int] = set()
    seats: set[int] = set()

    for name, result in tool_results:
        if name == "find_shows" and isinstance(result, list):
            shows.update(
                show["show_id"] for show in result if isinstance(show, dict)
            )

        elif name == "get_show_availability" and isinstance(result, dict):
            if "error" not in result and "show_id" in result:
                shows.add(result["show_id"])

        elif name == "rank_seats" and isinstance(result, dict):
            groups = result.get("groups") or []
            if groups and "show_id" in result:
                shows.add(result["show_id"])
            for group in groups:
                seats.update(group.get("seat_ids", []))

    return shows, seats


def _verify_options(
    options: list[ShowOption | SeatOption], tool_results: list[tuple[str, Any]]
) -> list[ShowOption | SeatOption]:
    """Drop any option whose ids did not come out of a tool result.

    Belt and braces: `_collect_options` already builds from tool results, so
    in the ordinary case nothing is dropped. It exists because the ordinary
    case is one refactor away from options being assembled somewhere looser,
    and because a wrong seat id is not a cosmetic bug -- it sends someone to
    a seat map that pre-selects a seat that is not there.
    """
    shows, seats = _ledger(tool_results)
    kept: list[ShowOption | SeatOption] = []

    for option in options:
        if option.show_id not in shows:
            logger.warning(
                "assistant dropped a fabricated option: show %s never came "
                "from a tool result",
                option.show_id,
            )
            continue

        if isinstance(option, SeatOption):
            invented = [
                seat_id for seat_id in option.seat_ids if seat_id not in seats
            ]
            if invented:
                logger.warning(
                    "assistant dropped a fabricated option: seats %s never "
                    "came from a tool result",
                    invented,
                )
                continue

        kept.append(option)

    return kept


# ------------------------------------------------------------------ chat


# --------------------------------------------------------- the provider


async def _complete(messages: list[dict[str, Any]]) -> Any:
    """Send one turn to the model and return its assistant message.

    THE ONLY PLACE THE PROVIDER IS NAMED. Groq speaks the OpenAI wire
    protocol, so the whole integration is the `openai` SDK pointed at a
    different base URL -- moving to another compatible provider, or back to
    OpenAI itself, is this function and two settings, not a rewrite.

    Upstream failures are translated here too, so the loop above deals in
    AppError and never in a vendor's exception hierarchy.
    """
    client = openai.AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        # A customer is waiting on this behind a spinner; a slow answer is
        # worse than a prompt "try again".
        timeout=45.0,
        max_retries=2,
    )

    try:
        response = await client.chat.completions.create(
            model=settings.groq_model,
            max_tokens=2048,
            # Low, not zero: the reply is prose, but the tool arguments need
            # to be reliable and the options come from the database anyway.
            temperature=0.2,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
    except openai.RateLimitError as exc:
        raise AppError(
            ErrorCode.CONFLICT,
            "The assistant is busy. Try again in a moment.",
            429,
            {"retry_after_seconds": 30},
        ) from exc
    except openai.APIStatusError as exc:
        logger.exception("assistant upstream error")
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "The assistant could not answer just now.",
            503,
            {"reason": "upstream_error", "status": exc.status_code},
        ) from exc
    except openai.APIConnectionError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Could not reach the assistant service.",
            503,
            {"reason": "upstream_unreachable"},
        ) from exc

    if not response.choices:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "The assistant could not answer just now.",
            503,
            {"reason": "empty_completion"},
        )
    return response.choices[0].message


def _assistant_turn(message: Any, calls: list[Any]) -> dict[str, Any]:
    """Rebuild the assistant turn as a plain dict to send back.

    Built field by field rather than round-tripping the SDK object: the turn
    has to survive being handed to a different provider, and `content` being
    None on a pure tool-call turn is exactly the sort of thing one accepts
    and another rejects.
    """
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in calls
        ],
    }


# ------------------------------------------------------------------ chat


async def chat(
    session: AsyncSession, request: ChatRequest, user_id: int
) -> ChatResponse:
    if not assistant_available():
        raise unavailable()

    # The system prompt is a message with role "system" here, not a top-level
    # parameter -- and it stays first so it remains a stable cache prefix.
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        _today_message(),
    ]

    # Oldest turns fall off first: the recent ones carry the constraints the
    # customer is still refining.
    history = request.conversation[-settings.assistant_max_history_turns * 2 :]
    messages.extend(
        {"role": turn.role, "content": turn.content} for turn in history
    )
    messages.append({"role": "user", "content": request.message})

    tool_calls_made: list[str] = []
    tool_results: list[tuple[str, Any]] = []
    reply = ""

    for _ in range(settings.assistant_max_iterations):
        message = await _complete(messages)

        # Keep the text from every turn, so a final answer is not lost if the
        # model stops on tool use in the last permitted iteration.
        if message.content and message.content.strip():
            reply = message.content.strip()

        calls = list(message.tool_calls or [])
        if not calls:
            break

        messages.append(_assistant_turn(message, calls))

        for call in calls:
            name = call.function.name
            tool_calls_made.append(name)

            try:
                arguments = _parse_arguments(call.function.arguments)
            except MalformedToolCall as exc:
                # The model broke its own contract. Stop, and ask for a
                # rephrase -- retrying the same prompt tends to produce the
                # same mangled call, and a 500 blames the customer's request
                # for the model's mistake.
                logger.warning(
                    "assistant sent unreadable arguments for %s: %s", name, exc
                )
                return ChatResponse(
                    reply=REPHRASE_REPLY,
                    options=[],
                    tool_calls_made=tool_calls_made,
                )

            # Off by default; invaluable when a weaker model is filling the
            # arguments in badly rather than not at all.
            logger.debug("assistant tool call %s(%s)", name, arguments)
            result = await _run_tool(session, name, arguments, user_id)
            tool_results.append((name, result))

            # One message per result, each carrying its tool_call_id. Unlike
            # the Anthropic shape, these are separate messages rather than
            # blocks in one -- but the provider still matches them up by id,
            # so parallel tool calls cost the same single round trip.
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    if not reply:
        reply = (
            "I could not put together an answer for that. Try naming a film, "
            "a city, or how many seats you need."
        )

    options = _verify_options(_collect_options(tool_results), tool_results)

    return ChatResponse(
        reply=reply,
        options=options,
        tool_calls_made=tool_calls_made,
    )
