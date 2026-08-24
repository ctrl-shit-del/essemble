"""The AI assistant: read-only tools, ranking, and the guard rails.

The tool tests hit the real database. The loop tests stub the model client --
the point of those is the orchestration and the security boundary, and paying
for a model round trip on every CI run to assert our own plumbing would be a
poor trade.

The client is the OpenAI SDK pointed at Groq, so the fakes below wear the
OpenAI response shape: choices[0].message, tool_calls[], and arguments as a
JSON *string*. That string is the reason two of these tests exist -- it is a
place a weaker model can hand back something unparseable.
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.assistant import service, tools
from app.assistant.schemas import ChatRequest
from app.core.config import settings
from app.core.db import SessionFactory, engine

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ------------------------------------------------------------- fixtures


async def a_future_show(world) -> int:
    """A scheduled show with seats, from the seeded world."""
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT id FROM show WHERE status = 'scheduled'"
                    " AND starts_at > now() ORDER BY starts_at LIMIT 1"
                )
            )
        ).scalar_one()


async def user_id_for(email: str) -> int:
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT id FROM user_account WHERE email = :e"), {"e": email}
            )
        ).scalar_one()


class FakeCompletions:
    """Stands in for client.chat.completions, replaying scripted turns."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._turns.pop(0)


class FakeClient:
    def __init__(self, turns):
        self.completions = FakeCompletions(turns)
        self.chat = self

    @property
    def calls(self):
        return self.completions.calls


def _completion(content, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls)
            )
        ]
    )


def text_turn(body: str):
    return _completion(body)


def tool_turn(name: str, payload: dict, call_id: str = "call_1"):
    """A well-formed call: arguments are a JSON string, as on the wire."""
    return raw_tool_turn(name, json.dumps(payload), call_id)


def raw_tool_turn(name: str, arguments, call_id: str = "call_1"):
    """A call with the arguments string passed through verbatim.

    Lets a test hand the loop the truncated or non-JSON string a smaller
    model actually emits.
    """
    return _completion(
        None,
        [
            SimpleNamespace(
                id=call_id,
                type="function",
                function=SimpleNamespace(name=name, arguments=arguments),
            )
        ],
    )


def use_fake(monkeypatch, fake):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(service.openai, "AsyncOpenAI", lambda **kwargs: fake)


# ----------------------------------------------------------- find_shows


async def test_a_budget_query_returns_only_options_within_it(world):
    """A price ceiling is a filter, not a hint."""
    async with SessionFactory() as session:
        cheap = await tools.find_shows(session, max_price="300.00")
        assert cheap, "the seed has shows from 250, so this must match"
        for show in cheap:
            assert Decimal(show["from_price"]) <= Decimal("300.00")

        # And the ceiling genuinely excludes something.
        everything = await tools.find_shows(session)
        assert len(cheap) <= len(everything)

        impossible = await tools.find_shows(session, max_price="1.00")
        assert impossible == []


async def test_find_shows_never_returns_a_show_that_has_started(world):
    async with SessionFactory() as session:
        shows = await tools.find_shows(session, date_from=None, date_to=None)
    async with engine.begin() as conn:
        now = (await conn.execute(text("SELECT now()"))).scalar_one()
    for show in shows:
        from datetime import datetime

        assert datetime.fromisoformat(show["starts_at"]) > now


# ----------------------------------------------------------- rank_seats


async def test_rank_seats_never_returns_non_adjacent_seats(world):
    """Adjacency is a hard requirement, not a scoring preference."""
    show_id = await a_future_show(world)

    async with SessionFactory() as session:
        for qty in (2, 3):
            result = await tools.rank_seats(session, show_id=show_id, qty=qty)
            assert result["groups"], f"expected candidates for qty={qty}"

            for group in result["groups"]:
                assert len(group["seat_ids"]) == qty

                async with engine.begin() as conn:
                    rows = (
                        await conn.execute(
                            text(
                                "SELECT row_label, x FROM seat"
                                " WHERE id = ANY(:ids) ORDER BY x"
                            ),
                            {"ids": group["seat_ids"]},
                        )
                    ).all()

                # One row, and consecutive x with no gap -- which also means
                # nobody in the party is seated across an aisle.
                assert len({r.row_label for r in rows}) == 1
                xs = [r.x for r in rows]
                assert xs == list(range(xs[0], xs[0] + qty))


async def test_rank_seats_returns_nothing_rather_than_splitting_a_party(world):
    """The hard requirement holds even when honouring it means no answer.

    The fixture screen is 6 seats a row with an aisle after the third, so the
    longest contiguous run is 3. A party of 4 therefore CANNOT sit together,
    and the correct response is no groups -- not four seats split across the
    aisle, and not two pairs in different rows.
    """
    show_id = await a_future_show(world)
    async with SessionFactory() as session:
        result = await tools.rank_seats(session, show_id=show_id, qty=4)

    assert result["groups"] == []
    assert result["reason"] == "no_adjacent_group_within_constraints"


async def test_rank_seats_never_returns_a_held_or_booked_seat(world):
    """Availability is derived the same way the seat map derives it."""
    show_id = await a_future_show(world)

    # Take a real hold through the API, exactly as another customer would.
    async with SessionFactory() as session:
        before = await tools.rank_seats(session, show_id=show_id, qty=2)
    taken = before["groups"][0]["seat_ids"]

    r = await world.client.post(
        "/api/holds",
        headers=world.auth("bob"),
        json={"show_id": show_id, "seat_ids": taken},
    )
    assert r.status_code == 201, r.text

    async with SessionFactory() as session:
        after = await tools.rank_seats(session, show_id=show_id, qty=2)

    offered = {seat for group in after["groups"] for seat in group["seat_ids"]}
    assert not (offered & set(taken)), "a held seat was offered to someone else"

    # And a booked seat is just as invisible.
    group_id = r.json()["hold_group_id"]
    r = await world.client.post(
        f"/api/holds/{group_id}/confirm", headers=world.auth("bob")
    )
    assert r.status_code == 201

    async with SessionFactory() as session:
        after_booking = await tools.rank_seats(session, show_id=show_id, qty=2)
    offered = {
        seat for group in after_booking["groups"] for seat in group["seat_ids"]
    }
    assert not (offered & set(taken))


async def test_rank_seats_respects_a_total_budget(world):
    show_id = await a_future_show(world)
    async with SessionFactory() as session:
        result = await tools.rank_seats(
            session, show_id=show_id, qty=2, max_total="600.00"
        )
    for group in result["groups"]:
        assert Decimal(group["total"]) <= Decimal("600.00")


async def test_rank_seats_is_deterministic(world):
    """Same question, same answer -- ranking is computed, not sampled."""
    show_id = await a_future_show(world)
    async with SessionFactory() as session:
        first = await tools.rank_seats(session, show_id=show_id, qty=2)
        second = await tools.rank_seats(session, show_id=show_id, qty=2)
    assert [g["seat_ids"] for g in first["groups"]] == [
        g["seat_ids"] for g in second["groups"]
    ]


async def test_rank_seats_returns_the_score_components(world):
    """The assistant explains WHY from these numbers rather than inventing."""
    show_id = await a_future_show(world)
    async with SessionFactory() as session:
        result = await tools.rank_seats(session, show_id=show_id, qty=2)
    breakdown = result["groups"][0]["score_breakdown"]
    assert {"adjacency", "centrality", "depth", "budget_fit", "category_rank"} <= set(
        breakdown
    )


# ------------------------------------------------------- user context


async def test_get_user_context_is_empty_rather_than_guessed_for_a_new_user(world):
    async with SessionFactory() as session:
        context = await tools.get_user_context(
            session, user_id=await user_id_for("carol@t.dev")
        )
    assert context["has_history"] is False
    assert "usual_party_size" not in context


async def test_get_user_context_describes_only_the_caller(world):
    """The model cannot address another customer, structurally.

    There is no user_id in the tool schema at all, so there is no field for
    it to fill in -- and the dispatcher ignores whatever the model sends.
    """
    assert not any("user_id" in str(schema) for schema in service.TOOL_SCHEMAS)

    alice = await user_id_for("alice@t.dev")
    bob = await user_id_for("bob@t.dev")

    # Book something as alice so the two users have different histories.
    show_id = await a_future_show(world)
    async with SessionFactory() as session:
        groups = await tools.rank_seats(session, show_id=show_id, qty=1)
    r = await world.client.post(
        "/api/holds",
        headers=world.auth("alice"),
        json={"show_id": show_id, "seat_ids": groups["groups"][0]["seat_ids"]},
    )
    assert r.status_code == 201
    await world.client.post(
        f"/api/holds/{r.json()['hold_group_id']}/confirm",
        headers=world.auth("alice"),
    )

    async with SessionFactory() as session:
        # The model asks for bob's history while alice is the caller.
        result = await service._run_tool(
            session, "get_user_context", {"user_id": bob}, user_id=alice
        )

    async with SessionFactory() as session:
        alice_context = await tools.get_user_context(session, user_id=alice)

    # It answered about the CALLER, ignoring the argument entirely.
    assert result == alice_context
    assert result["has_history"] is True


# ------------------------------------------------------------ the loop


async def test_asking_to_just_book_it_returns_options_not_a_booking(
    world, monkeypatch
):
    """The assistant hands back an option; it never books."""
    show_id = await a_future_show(world)

    async with engine.begin() as conn:
        before = (
            await conn.execute(text("SELECT count(*) FROM booking"))
        ).scalar_one()
        claims_before = (
            await conn.execute(text("SELECT count(*) FROM seat_claim"))
        ).scalar_one()

    fake = FakeClient(
        [
            tool_turn("rank_seats", {"show_id": show_id, "qty": 2}),
            text_turn(
                "I can't book for you, but these two are the best of what's "
                "free. Tap one and press hold."
            ),
        ]
    )
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        response = await service.chat(
            session,
            ChatRequest(message="just book it for me", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    assert "can't book" in response.reply
    assert response.options, "it must hand back options"
    assert all(option.kind == "seats" for option in response.options)
    assert response.tool_calls_made == ["rank_seats"]

    # NOTHING was written.
    async with engine.begin() as conn:
        assert (
            await conn.execute(text("SELECT count(*) FROM booking"))
        ).scalar_one() == before
        assert (
            await conn.execute(text("SELECT count(*) FROM seat_claim"))
        ).scalar_one() == claims_before


async def test_the_loop_stops_at_the_iteration_cap(world, monkeypatch):
    """A model that keeps calling tools must not loop forever."""
    show_id = await a_future_show(world)
    fake = FakeClient(
        [tool_turn("get_show_availability", {"show_id": show_id})] * 10
    )
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        await service.chat(
            session,
            ChatRequest(message="what is on", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    assert len(fake.calls) == settings.assistant_max_iterations


async def test_history_is_truncated_to_the_configured_turns(world, monkeypatch):
    from app.assistant.schemas import ChatTurn

    fake = FakeClient([text_turn("ok")])
    use_fake(monkeypatch, fake)

    long_history = [
        ChatTurn(role="user" if i % 2 == 0 else "assistant", content=f"turn {i}")
        for i in range(40)
    ]

    async with SessionFactory() as session:
        await service.chat(
            session,
            ChatRequest(message="and now?", conversation=long_history),
            user_id=await user_id_for("alice@t.dev"),
        )

    sent = fake.calls[0]["messages"]
    # The system prompt is a message here, not a top-level parameter, and it
    # stays first so it remains a stable cache prefix.
    assert sent[0]["role"] == "system"
    # Two system messages: the prompt, then today's date.
    assert sent[1]["role"] == "system"
    # both system messages + history window + the new message
    assert len(sent) == settings.assistant_max_history_turns * 2 + 3
    assert sent[-1]["content"] == "and now?"
    # The OLDEST turns are the ones dropped.
    assert "turn 0" not in str(sent)


# ------------------------------------------------------ configuration


async def test_missing_api_key_gives_503_on_the_assistant_only(world, monkeypatch):
    """A missing key disables one feature, not the product."""
    monkeypatch.setattr(settings, "groq_api_key", None)
    service.reset_rate_limits()

    r = await world.client.post(
        "/api/assistant/chat",
        headers=world.auth("alice"),
        json={"message": "anything on tonight?", "conversation": []},
    )
    assert r.status_code == 503
    assert r.json()["error"]["details"]["reason"] == "missing_api_key"

    # Everything else is completely unaffected.
    for path in ("/health", "/api/health", "/api/events"):
        assert (await world.client.get(path)).status_code == 200
    assert (
        await world.client.get(f"/api/shows/{await a_future_show(world)}/seatmap")
    ).status_code == 200


async def test_the_assistant_is_rate_limited(world, monkeypatch):
    monkeypatch.setattr(settings, "assistant_rate_limit_per_hour", 3)
    service.reset_rate_limits()

    user_id = await user_id_for("alice@t.dev")
    for _ in range(3):
        service.check_rate_limit(user_id)

    from app.core.errors import AppError

    with pytest.raises(AppError) as caught:
        service.check_rate_limit(user_id)
    assert caught.value.status_code == 429
    assert caught.value.details["retry_after_seconds"] > 0
    service.reset_rate_limits()


async def test_the_assistant_has_no_write_tools():
    """The constraint, asserted rather than trusted to review.

    If someone later adds a booking tool, this fails.
    """
    import inspect

    # The OpenAI envelope: {"type": "function", "function": {...}}.
    assert all(schema["type"] == "function" for schema in service.TOOL_SCHEMAS)
    names = {schema["function"]["name"] for schema in service.TOOL_SCHEMAS}
    assert names == {
        "find_shows",
        "get_show_availability",
        "rank_seats",
        "get_user_context",
    }

    # Scan the CODE, not the prose. The module documents this very constraint
    # in its own docstring, and a naive substring search would match that --
    # passing or failing for entirely the wrong reason.
    import ast

    tree = ast.parse(inspect.getsource(tools))
    for node in ast.walk(tree):
        # Drop every docstring: an expression statement that is just a string.
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                body.pop(0)

    code = ast.unparse(tree).upper()
    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", ".COMMIT("):
        assert forbidden not in code, f"tools.py appears to write: {forbidden}"


async def test_the_system_prompt_states_it_cannot_book():
    from app.assistant.prompts import SYSTEM_PROMPT

    assert "CANNOT book" in SYSTEM_PROMPT
    assert "no tools that write" in SYSTEM_PROMPT


# ------------------------------------ guards for a weaker model


async def test_malformed_tool_arguments_ask_for_a_rephrase(world, monkeypatch):
    """A truncated arguments string is not a 500.

    `function.arguments` arrives as a JSON string and a smaller model
    sometimes cuts it off mid-object. That is the model breaking its own
    contract, not the customer's request being wrong, so the customer gets a
    plain ask to try again.
    """
    fake = FakeClient([raw_tool_turn("rank_seats", '{"show_id": 3, "qty":')])
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        response = await service.chat(
            session,
            ChatRequest(message="two seats please", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    assert response.reply == service.REPHRASE_REPLY
    assert response.options == []
    # The attempt is still reported: the interface says what actually ran.
    assert response.tool_calls_made == ["rank_seats"]


async def test_non_json_tool_arguments_ask_for_a_rephrase(world, monkeypatch):
    """Prose where JSON was promised gets the same treatment."""
    fake = FakeClient(
        [raw_tool_turn("find_shows", "Sure! Let me search for that.")]
    )
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        response = await service.chat(
            session,
            ChatRequest(message="what is on", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    assert response.reply == service.REPHRASE_REPLY


async def test_empty_arguments_are_a_valid_no_argument_call(world, monkeypatch):
    """get_user_context takes nothing, so "" must not be an error."""
    fake = FakeClient(
        [
            raw_tool_turn("get_user_context", ""),
            text_turn("You usually book two."),
        ]
    )
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        response = await service.chat(
            session,
            ChatRequest(message="the usual", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    assert response.reply == "You usually book two."
    assert response.tool_calls_made == ["get_user_context"]


async def test_an_invented_id_never_reaches_the_customer(world):
    """The hallucination guard, asserted on its own.

    `_collect_options` builds from tool results, so nothing is dropped in the
    ordinary case. This proves the guard actually bites when an option's ids
    did not come from the database -- a wrong seat id is not cosmetic, it
    sends someone to a seat map that pre-selects a seat that is not there.
    """
    from app.assistant.schemas import SeatOption, ShowOption

    show_id = await a_future_show(world)
    async with SessionFactory() as session:
        ranked = await tools.rank_seats(session, show_id=show_id, qty=2)

    real_group = ranked["groups"][0]
    tool_results = [("rank_seats", ranked)]

    def seat_option(sid, seat_ids):
        return SeatOption(
            show_id=sid,
            seat_ids=seat_ids,
            seats=["Z1", "Z2"],
            row="Z",
            category="Invented",
            category_id=1,
            price_per_seat="100.00",
            total="200.00",
            reason="because the model said so",
            score_breakdown={},
        )

    genuine = seat_option(show_id, real_group["seat_ids"])
    invented_seats = seat_option(show_id, [999_001, 999_002])
    invented_show = ShowOption(
        show_id=999_999,
        title="A Film That Does Not Exist",
        venue="Nowhere",
        screen="1",
        starts_at="2099-01-01T00:00:00+00:00",
        language="English",
        seats_available=100,
    )

    kept = service._verify_options(
        [genuine, invented_seats, invented_show], tool_results
    )

    assert kept == [genuine]


async def test_the_ledger_ignores_ids_the_model_merely_asked_about(world):
    """An argument is not evidence.

    rank_seats echoes back the show_id it was given. If it found no groups,
    that echo proves nothing -- it is just the number the model supplied,
    and admitting it would launder a guess into a fact.
    """
    shows, seats = service._ledger(
        [("rank_seats", {"show_id": 424_242, "groups": []})]
    )
    assert shows == set()
    assert seats == set()


# ------------------------------------------- grounding the model


async def test_the_loop_tells_the_model_what_today_is(world, monkeypatch):
    """The date is injected, in the timezone the catalogue is written in.

    Left to itself the model guesses the date, and a guess a day out turns
    "anything on tonight" into a confident "nothing is on".
    """
    from datetime import datetime

    fake = FakeClient([text_turn("ok")])
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        await service.chat(
            session,
            ChatRequest(message="anything on tonight?", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    sent = fake.calls[0]["messages"]
    # The prompt stays first so it remains a stable cache prefix; the date,
    # which changes every minute, goes in a message of its own after it.
    assert sent[0]["content"] == service.SYSTEM_PROMPT
    assert sent[1]["role"] == "system"

    now = datetime.now(service.IST)
    assert now.date().isoformat() in sent[1]["content"]
    assert now.strftime("%A") in sent[1]["content"]
    assert "IST" in sent[1]["content"]


async def test_tonight_resolves_to_today_not_yesterday(world, monkeypatch):
    """A query for "tonight" reaches find_shows with date_from == today.

    The stand-in model does what a real one is asked to do: read the date out
    of the injected message and search that day. So this proves the date is
    present, correctly formatted, in the right timezone, and reaches the tool
    -- the plumbing that was broken. It does not prove a given model bothers
    to read it; that is checked against the live API.
    """
    import re
    from datetime import datetime

    captured: dict = {}
    real_find_shows = tools.find_shows

    async def spy(session, **kwargs):
        captured.update(kwargs)
        return await real_find_shows(session, **kwargs)

    monkeypatch.setattr(service.tools, "find_shows", spy)

    class DateReadingClient:
        """Resolves "tonight" from the injected message, as instructed."""

        def __init__(self):
            self.completions = self
            self.chat = self
            self.calls: list[dict] = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) > 1:
                return text_turn("Here's what's on.")
            grounding = " ".join(
                m["content"]
                for m in kwargs["messages"]
                if m["role"] == "system"
            )
            found = re.search(r"Today is (\d{4}-\d{2}-\d{2})", grounding)
            assert found, "nothing told the model what day it is"
            today = found.group(1)
            return tool_turn(
                "find_shows", {"date_from": today, "date_to": today}
            )

    fake = DateReadingClient()
    use_fake(monkeypatch, fake)

    async with SessionFactory() as session:
        await service.chat(
            session,
            ChatRequest(message="anything on tonight?", conversation=[]),
            user_id=await user_id_for("alice@t.dev"),
        )

    assert captured["date_from"] == datetime.now(service.IST).date()


# ------------------------------------------------ genre filtering


#: Deliberately overlapping: "Sci-Fi" lands on two different events, so a
#: filter that quietly did equality instead of overlap would still pass the
#: single-genre test and fail these.
_TAGS = [["Sci-Fi", "Thriller"], ["Comedy"], ["Drama", "Sci-Fi"]]


@pytest.fixture
async def tagged_events(world):
    """Give the seeded events genres, and put the originals back.

    `event` is not one of the tables the world fixture truncates, so a test
    that stamps genres onto it would leak into every test after it.
    """
    async with engine.begin() as conn:
        before = (
            await conn.execute(text("SELECT id, genres FROM event ORDER BY id"))
        ).all()
        assert before, "no events to tag"
        for index, (event_id, _) in enumerate(before):
            await conn.execute(
                text("UPDATE event SET genres = :g WHERE id = :i"),
                {"g": _TAGS[index % len(_TAGS)], "i": event_id},
            )
    try:
        yield
    finally:
        async with engine.begin() as conn:
            for event_id, genres in before:
                await conn.execute(
                    text("UPDATE event SET genres = :g WHERE id = :i"),
                    {"g": list(genres or []), "i": event_id},
                )


async def test_a_genre_filter_returns_only_shows_carrying_that_genre(world, tagged_events):
    """The filter genres actually had nowhere to go before this."""
    async with SessionFactory() as session:
        everything = await tools.find_shows(session)
        genres_present = {
            genre for show in everything for genre in show["genres"]
        }
        assert genres_present, "the fixture has no genres to filter on"
        wanted = sorted(genres_present)[0]

        matching = await tools.find_shows(session, genres=[wanted])

    assert matching, f"nothing came back for {wanted!r}"
    for show in matching:
        assert wanted in show["genres"]

    # Overlap, not equality: it must not have narrowed to shows whose ONLY
    # genre is the requested one.
    expected = [s for s in everything if wanted in s["genres"]]
    assert {s["show_id"] for s in matching} == {s["show_id"] for s in expected}


async def test_several_genres_match_a_show_carrying_any_one_of_them(world, tagged_events):
    async with SessionFactory() as session:
        everything = await tools.find_shows(session)
        pair = sorted({g for s in everything for g in s["genres"]})[:2]
        matching = await tools.find_shows(session, genres=pair)

    for show in matching:
        assert set(pair) & set(show["genres"]), (
            f"{show['title']!r} carries {show['genres']}, none of {pair}"
        )
    expected = {
        s["show_id"] for s in everything if set(pair) & set(s["genres"])
    }
    assert {s["show_id"] for s in matching} == expected


async def test_genre_matching_survives_the_model_retyping_the_casing(world, tagged_events):
    """The model retypes these from get_user_context; its casing drifts."""
    async with SessionFactory() as session:
        everything = await tools.find_shows(session)
        wanted = sorted({g for s in everything for g in s["genres"]})[0]

        exact = await tools.find_shows(session, genres=[wanted])
        shouted = await tools.find_shows(session, genres=[wanted.upper()])
        whispered = await tools.find_shows(session, genres=[wanted.lower()])
        # A bare string where a list was asked for, which happens.
        bare = await tools.find_shows(session, genres=wanted)

    ids = {s["show_id"] for s in exact}
    assert ids
    for variant in (shouted, whispered, bare):
        assert {s["show_id"] for s in variant} == ids


async def test_an_empty_genre_list_is_not_a_filter(world, tagged_events):
    """[] means "no preference", not "match nothing"."""
    async with SessionFactory() as session:
        unfiltered = await tools.find_shows(session)
        empty = await tools.find_shows(session, genres=[])
        blanks = await tools.find_shows(session, genres=["", "  "])

    assert {s["show_id"] for s in empty} == {s["show_id"] for s in unfiltered}
    assert {s["show_id"] for s in blanks} == {s["show_id"] for s in unfiltered}
