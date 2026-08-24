"""Configuration and API-surface completeness.

These are documentation tests. They fail when the code and the things an
evaluator reads -- .env.example, the OpenAPI schema -- drift apart, which is
the failure mode nobody notices until someone tries to deploy from the repo.
"""

import pathlib
import re

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError

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


# ------------------------------------------------------------------- CORS


def test_cors_origins_parses_a_comma_separated_list():
    """pydantic-settings would otherwise JSON-decode a list-typed setting.

    `CORS_ORIGINS=http://a,http://b` is not JSON, so without NoDecode plus the
    validator this raises during settings construction -- at import time, with
    no route to catch it.
    """
    parsed = Settings(cors_origins="http://localhost:3000, https://x.vercel.app ,")
    assert parsed.cors_origins == ["http://localhost:3000", "https://x.vercel.app"]


def test_cors_origins_reads_a_comma_separated_environment_variable(monkeypatch):
    """The constructor and the environment take different code paths."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,https://x.vercel.app")
    assert Settings().cors_origins == [
        "http://localhost:3000",
        "https://x.vercel.app",
    ]


def test_cors_origins_defaults_to_the_local_frontend():
    assert Settings().cors_origins == ["http://localhost:3000"]


def test_cors_is_never_configured_as_a_credentialed_wildcard():
    """A wildcard would break CORS here, not loosen it.

    The API sends allow_credentials=True, and a browser refuses
    `Access-Control-Allow-Origin: *` on a credentialed request. A "*" in the
    configured origins is therefore a misconfiguration that fails only in the
    browser, which is the worst place to find it.
    """
    from app.main import app
    from starlette.middleware.cors import CORSMiddleware

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1, "CORS middleware is not installed exactly once"

    options = cors[0].kwargs
    assert options["allow_credentials"] is True
    assert "*" not in options["allow_origins"], (
        "allow_origins=['*'] is incompatible with allow_credentials=True"
    )
    assert options["allow_origins"], "no origins configured"


@session_loop
async def test_preflight_and_actual_request_carry_cors_headers(world):
    """End to end: what a browser actually sees."""
    origin = Settings().cors_origins[0]

    preflight = await world.client.options(
        "/api/holds",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code in (200, 204), preflight.text
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["access-control-allow-credentials"] == "true"

    actual = await world.client.get(
        f"/api/shows/{world.show_id}/seatmap", headers={"Origin": origin}
    )
    assert actual.status_code == 200
    assert actual.headers["access-control-allow-origin"] == origin


def test_an_unlisted_origin_is_not_echoed_back():
    """The allowlist has to actually exclude something."""
    from starlette.middleware.cors import CORSMiddleware

    from app.main import app

    options = [m for m in app.user_middleware if m.cls is CORSMiddleware][0].kwargs
    assert "https://not-our-frontend.example" not in options["allow_origins"]


# ------------------------------------------------------- deployment files


def test_uvicorn_is_declared_as_a_dependency():
    """The server the deployment runs must be installed by the deployment."""
    requirements = pathlib.Path("requirements.txt").read_text()
    assert "uvicorn" in requirements


def test_runtime_txt_pins_an_interpreter():
    """.python-version is not honoured by every host; runtime.txt is."""
    runtime = pathlib.Path("runtime.txt").read_text().strip()
    assert re.fullmatch(r"python-3\.\d+\.\d+", runtime), runtime


def test_the_start_command_binds_all_interfaces_on_the_assigned_port():
    """Binding loopback, or a hardcoded port, makes the service unroutable.

    Neither failure shows up in the application log -- the process starts
    happily and the platform's health check simply never connects.
    """
    for path in ("Procfile", "scripts/start.sh"):
        # Executable lines only: the comments in these files discuss the very
        # mistakes being asserted against.
        command = " ".join(
            line
            for line in pathlib.Path(path).read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        assert "0.0.0.0" in command, f"{path} does not bind 0.0.0.0"
        assert "127.0.0.1" not in command, f"{path} binds loopback"
        assert "localhost" not in command, f"{path} binds localhost"
        assert "PORT" in command, f"{path} does not use $PORT"
        assert not re.search(r"--port\s+\d+", command), f"{path} hardcodes a port"


# -------------------------------------------------------- test isolation


def test_the_suite_is_not_running_against_the_application_database():
    """A standing assertion, not a one-off check.

    conftest refuses to start when the two DSNs match, but that guard reads
    the environment. This reads the Settings the app actually built, so it
    also catches the case where something re-pointed the engine after the
    bootstrap ran.
    """
    from app.core.config import settings

    env = dotenv_values(".env")
    app_dsn = (env.get("DATABASE_URL") or "").strip()
    if not app_dsn:
        pytest.skip("no DATABASE_URL in .env to compare against")

    from tests.conftest import _endpoint

    assert _endpoint(settings.database_url) != _endpoint(app_dsn), (
        "the suite is pointed at the application database and would truncate it"
    )


def test_the_test_database_is_a_direct_endpoint():
    """LISTEN/NOTIFY does not survive transaction pooling.

    A pooled test DSN would fail the SSE tests specifically, and it would
    look like a bug in the broker rather than a configuration mistake.
    """
    from app.core.config import settings

    assert not settings.db_is_pooled, (
        f"the test database is a pooled endpoint ({settings.db_host}); "
        "the SSE tests need LISTEN/NOTIFY"
    )


# ------------------------------------------------------- required secrets

#: Both signing keys, with what an attacker gains if either is guessable.
SECRETS = ["jwt_secret", "qr_secret"]

#: Every way a secret can fail to be one.
BAD_VALUES = [
    pytest.param(None, id="unset"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace"),
    pytest.param("change-me-in-production", id="placeholder"),
    pytest.param("CHANGE-ME-IN-PRODUCTION", id="placeholder-uppercase"),
    pytest.param("changeme", id="placeholder-variant"),
    pytest.param("short", id="too-short"),
]

REAL = "K7q2wZ0pL9vX4nT8mB3sR6yH1jF5dC0a"


@pytest.mark.parametrize("field", SECRETS)
@pytest.mark.parametrize("value", BAD_VALUES)
def test_settings_refuses_to_exist_without_a_real_secret(field, value):
    """A default signing key is a key everyone with the repo already has.

    Unconditional, not scoped to ENVIRONMENT: scoping it would mean this path
    never runs locally or in CI, so its first execution would be the
    deployment it exists to protect.
    """
    kwargs = {name: REAL for name in SECRETS}
    kwargs[field] = value

    with pytest.raises(ValidationError) as caught:
        Settings(**kwargs)

    message = str(caught.value)
    assert field.upper() in message, "the error must name the variable"
    assert "secrets.token_urlsafe" in message, (
        "the error must say how to generate one"
    )


@pytest.mark.parametrize("field", SECRETS)
def test_a_real_secret_is_accepted(field):
    """The guard must not reject legitimate values."""
    kwargs = {name: REAL for name in SECRETS}
    assert getattr(Settings(**kwargs), field) == REAL


def test_the_placeholder_is_refused_even_in_a_local_environment():
    """The rule is unconditional. ENVIRONMENT does not soften it."""
    for environment in ("local", "staging", "production"):
        with pytest.raises(ValidationError):
            Settings(
                environment=environment,
                jwt_secret="change-me-in-production",
                qr_secret=REAL,
            )


def test_neither_secret_has_a_usable_default():
    """Nothing to fall back to: the field defaults are absence, not a value."""
    for field in SECRETS:
        default = Settings.model_fields[field].default
        assert default is None, f"{field} still has a default: {default!r}"


def test_env_example_ships_no_real_secret_value():
    """The example file must not carry something that would silently work."""
    for line in ENV_EXAMPLE.read_text().splitlines():
        for field in SECRETS:
            prefix = f"{field.upper()}="
            if line.startswith(prefix):
                assert line[len(prefix):].strip() == "", (
                    f"{prefix} in .env.example must be blank, not a value "
                    "someone could deploy with"
                )


def test_env_example_documents_how_to_generate_a_secret():
    assert "secrets.token_urlsafe" in ENV_EXAMPLE.read_text()
