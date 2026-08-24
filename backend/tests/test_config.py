"""Configuration and API-surface completeness.

These are documentation tests. They fail when the code and the things an
evaluator reads -- .env.example, the OpenAPI schema -- drift apart, which is
the failure mode nobody notices until someone tries to deploy from the repo.
"""

import pathlib
import re

import pytest

from app.core.config import Settings
from app.main import app

#: Only the database-backed tests below need the session-scoped loop; a
#: module-level mark would wrongly tag the sync ones too.
session_loop = pytest.mark.asyncio(loop_scope="session")

ENV_EXAMPLE = pathlib.Path(".env.example")

#: Settings fields that are deliberately absent from .env.example because
#: nothing should ever set them by hand. Empty today; kept so that adding an
#: exemption is a visible, commented decision rather than a silent edit.
NOT_CONFIGURABLE_BY_HAND: set[str] = set()


def env_example_keys() -> set[str]:
    """Every KEY= assignment in .env.example, comments ignored."""
    keys = set()
    for line in ENV_EXAMPLE.read_text().splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())
        if match:
            keys.add(match.group(1))
    return keys


def test_every_setting_is_documented_in_env_example():
    """A setting with no .env.example entry is invisible to a deployer.

    They cannot discover it from the README and will not read config.py, so
    it silently keeps its default in production.
    """
    expected = {
        name.upper() for name in Settings.model_fields
    } - {n.upper() for n in NOT_CONFIGURABLE_BY_HAND}
    missing = sorted(expected - env_example_keys())
    assert missing == [], (
        f"settings with no .env.example entry: {missing}"
    )


def test_env_example_has_no_keys_that_are_not_settings():
    """The reverse drift: a key that looks configurable but is ignored."""
    known = {name.upper() for name in Settings.model_fields}
    stray = sorted(env_example_keys() - known)
    assert stray == [], (
        f".env.example keys matching no Settings field: {stray}"
    )


# ------------------------------------------------------------- API surface

#: The domain vocabulary. Every route belongs to exactly one domain, and
#: audience-scoped routes carry the audience as a second tag.
DOMAIN_TAGS = {
    "auth",
    "catalog",
    "venues",
    "booking",
    "waitlist",
    "checkin",
    "system",
}
AUDIENCE_TAGS = {"admin", "organiser"}


def api_routes():
    """Every route this app serves, excluding FastAPI's own docs endpoints."""
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
            continue
        if not hasattr(route, "endpoint"):
            continue
        yield route


def test_every_route_is_tagged_from_the_domain_vocabulary():
    untagged = []
    unknown = []
    for route in api_routes():
        tags = set(getattr(route, "tags", []) or [])
        if not tags:
            untagged.append(route.path)
            continue
        if not tags & DOMAIN_TAGS:
            untagged.append(route.path)
        stray = tags - DOMAIN_TAGS - AUDIENCE_TAGS
        if stray:
            unknown.append((route.path, sorted(stray)))

    assert untagged == [], f"routes with no domain tag: {untagged}"
    assert unknown == [], f"routes with tags outside the vocabulary: {unknown}"


def test_every_route_declares_a_response_model():
    """An undeclared response is a blank box in /docs.

    The SSE stream is exempt: its body is an unbounded event stream, which
    has no response model to declare -- it declares a response_class instead.
    """
    undeclared = [
        route.path
        for route in api_routes()
        if getattr(route, "response_model", None) is None
        and not route.path.endswith("/stream")
    ]
    assert undeclared == [], f"routes with no response_model: {undeclared}"


def test_every_route_documents_the_error_codes_it_can_return():
    """A route that can fail must say how, in words an evaluator can read.

    Routes that can only succeed (or only fail on auth, which every
    authenticated route shares) are exempt via the allowlist below.
    """
    from app.core.errors import ErrorCode

    always_succeeds = {
        ("GET", "/api/auth/me"),
        ("GET", "/api/admin/venues"),
        ("GET", "/api/organiser/shows"),
        ("GET", "/api/organiser/venue-requests"),
        ("GET", "/api/admin/venue-requests"),
        ("GET", "/api/events"),
        ("GET", "/api/waitlist"),
        ("GET", "/api/bookings"),
        ("GET", "/health"),
        ("GET", "/api/health"),
    }
    known = {code.value for code in ErrorCode}

    missing = []
    for route in api_routes():
        methods = getattr(route, "methods", set()) or set()
        for method in methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in always_succeeds:
                continue
            doc = (route.endpoint.__doc__ or "")
            if not any(f"`{code}`" in doc for code in known):
                missing.append(f"{method} {route.path}")

    assert sorted(missing) == [], (
        "routes whose docstring lists no error code: " + ", ".join(sorted(missing))
    )


# ------------------------------------------------------------ health detail


@session_loop
async def test_health_detail_reports_migration_workers_and_outbox(world):
    """The hosted instance must be able to prove its workers are alive."""
    r = await world.client.get("/api/health")
    assert r.status_code == 200
    body = r.json()

    assert body["database"] == "up"
    assert body["status"] == "ok"
    # The revision the database is actually at, not the one on disk.
    assert body["migration_revision"], "no alembic revision reported"
    assert isinstance(body["pending_outbox"], int)

    for worker in ("sweeper", "outbox"):
        assert set(body[worker]) == {"enabled", "interval_seconds", "last_run_at"}
        assert body[worker]["interval_seconds"] > 0


@session_loop
async def test_health_detail_reports_a_worker_that_has_run(world):
    """last_run_at moves from null to a timestamp once a tick completes.

    Under test the scheduler is off, so this drives run_tick directly -- the
    point is that the field reflects real work in this process rather than
    configuration.
    """
    from app.workers import sweeper

    before = (await world.client.get("/api/health")).json()["sweeper"]["last_run_at"]
    await sweeper.run_tick()
    after = (await world.client.get("/api/health")).json()["sweeper"]["last_run_at"]

    assert after is not None
    if before is not None:
        assert after >= before
