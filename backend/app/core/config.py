"""Application configuration.

Everything configurable lives here and is sourced from the environment via
pydantic-settings. Any new setting must also be added to .env.example.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: libpq spellings of sslmode and the asyncpg `ssl` value they map onto.
#: Managed Postgres providers hand out libpq URLs; asyncpg rejects sslmode.
_SSLMODE_TO_ASYNCPG = {
    "disable": "disable",
    "allow": "prefer",
    "prefer": "prefer",
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
}

#: Hostname fragments and ports that mean transaction-mode PgBouncer.
#: Neon puts "-pooler" in the host; Supabase uses port 6543.
_POOLED_HOST_MARKERS = ("-pooler",)
_POOLED_PORTS = (6543,)

#: Values that are not secrets. The first is the placeholder this project
#: shipped with; the rest are what a hurried deployment reaches for. Compared
#: case-insensitively after stripping whitespace.
_PLACEHOLDER_SECRETS = frozenset(
    {
        "change-me-in-production",
        "changeme",
        "change-me",
        "secret",
        "password",
        "test",
        "dev",
        "development",
        "production",
        "todo",
        "xxx",
        "none",
        "null",
    }
)

#: Short enough to brute-force offline. Both secrets are HMAC/HS256 keys, so
#: their whole value is that guessing them is infeasible.
_MIN_SECRET_LENGTH = 16

_MISSING_SECRET_ERROR = (
    "{name} is {problem}.\n"
    "\n"
    "This is refused rather than defaulted. {name} is a signing key: with a\n"
    "known value, {consequence}\n"
    "A default committed to the repository is a key that everyone who can\n"
    "read the repository already has, so there is no safe fallback to pick.\n"
    "\n"
    "Generate one and set it in the environment:\n"
    '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
    "\n"
    "Use a DIFFERENT value in each deployment, and never reuse the local one\n"
    "in production."
)

#: What an attacker gets for free if each secret is known.
_SECRET_CONSEQUENCE = {
    "JWT_SECRET": (
        "anyone can mint an access token for any user id and any\n"
        "role, including admin -- authentication stops meaning anything."
    ),
    "QR_SECRET": (
        "anyone can forge a check-in QR code for any booking\n"
        "reference, which is the whole of what stops a printed screenshot\n"
        "being a valid ticket (I8)."
    ),
}

_POOLED_DSN_ERROR = (
    "DATABASE_URL points at a transaction-mode connection pooler ({reason}).\n"
    "\n"
    "Use the direct endpoint instead:\n"
    "  Neon     -- same hostname with '-pooler' removed\n"
    "  Supabase -- port 5432 instead of 6543\n"
    "\n"
    "This is refused rather than silently rewritten because pooling breaks two\n"
    "things with no error of their own:\n"
    "  1. LISTEN/NOTIFY does not survive transaction pooling, so the SSE seat-map\n"
    "     stream would connect, stay open, and deliver nothing.\n"
    "  2. asyncpg prepared-statement caching fails against PgBouncer unless\n"
    "     statement_cache_size=0.\n"
    "Free-tier connection limits are not a concern at this concurrency."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- database -----------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://essemble:essemble@localhost:5432/essemble",
        description="Async SQLAlchemy DSN. Must use the asyncpg driver.",
    )
    #: Separate database for the test suite. The suite TRUNCATEs every
    #: application table at session start, so it must never be pointed at a
    #: database anything else is using -- a deployed instance runs a sweeper
    #: and an outbox dispatcher permanently, and those two workers racing a
    #: truncating test suite make every run flaky in both directions: the
    #: workers mutate rows mid-test, and the suite deletes the deployment's
    #: data. tests/conftest.py refuses to start without this set to a
    #: different endpoint from DATABASE_URL.
    test_database_url: str | None = None
    db_echo: bool = False
    #: Open and close a connection per use instead of pooling. The test suite
    #: sets this: pytest-asyncio gives each test its own event loop, and a
    #: pooled asyncpg connection belongs to the loop that opened it.
    db_use_null_pool: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- auth ---------------------------------------------------------------
    #: HS256 signing key for access tokens. NO DEFAULT, deliberately: a
    #: fallback value here is a signing key published in the repository, and
    #: anyone holding it can mint a token for any user id and any role.
    #: Absence is checked below and refused.
    jwt_secret: str | None = Field(
        default=None,
        description="HS256 signing key for access tokens. Required.",
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # --- booking ------------------------------------------------------------
    #: How long a seat hold survives without confirmation.
    hold_ttl_seconds: int = 600
    max_seats_per_hold: int = 10
    #: How long a waitlist offer stays claimable. The seats are held for the
    #: offer for exactly this long.
    waitlist_offer_ttl_seconds: int = 900
    #: A booking can no longer be cancelled this close to the show.
    cancellation_cutoff_minutes: int = 60
    #: HMAC key for QR payloads. A raw booking reference must never be enough
    #: to check in (I8), which is only true while this is secret. NO DEFAULT,
    #: for the same reason as jwt_secret: a published key means anyone can
    #: forge a ticket for any reference. Absence is checked below and refused.
    qr_secret: str | None = Field(
        default=None, description="HMAC key for QR payloads. Required."
    )

    # --- workers ------------------------------------------------------------
    sweeper_interval_seconds: int = 10
    outbox_interval_seconds: int = 5
    #: Workers run in-process via APScheduler. Disabled under test, where the
    #: sweep functions are called directly instead of waited on.
    workers_enabled: bool = True
    #: SSE fan-out. Needs a long-lived process and a direct (non-pooled)
    #: connection; the ?since poll path is the fallback when it is off.
    realtime_enabled: bool = True
    outbox_enabled: bool = True

    # --- mail ---------------------------------------------------------------
    #: 'console' prints the rendered email, so the app runs with no
    #: credentials at all. 'resend' delivers for real.
    mail_driver: Literal["console", "resend"] = "console"
    resend_api_key: str | None = None
    mail_from: str = "Essemble <tickets@essemble.dev>"

    # --- scheduling rules ---------------------------------------------------
    #: Gap enforced between two shows on the same screen, on top of runtime.
    show_buffer_minutes: int = 30
    #: Runtime assumed for an event that declares none (live events mostly).
    default_event_runtime_min: int = 120

    # --- app ----------------------------------------------------------------
    app_base_url: str = "http://localhost:8000"
    environment: Literal["local", "staging", "production"] = "local"

    #: Browser origins allowed to call this API, comma-separated in the
    #: environment.
    #:
    #: NoDecode turns off pydantic-settings' JSON decoding for this field.
    #: Without it a list-typed setting is JSON-parsed straight out of the
    #: environment, and `CORS_ORIGINS=http://a,http://b` fails to parse before
    #: any validator of ours gets to see it.
    #:
    #: There is deliberately no "*" default. `allow_credentials=True` and
    #: `allow_origins=["*"]` are mutually exclusive per the CORS spec -- the
    #: browser rejects a wildcard on a credentialed request -- so the origins
    #: have to be named. Add the deployed frontend's URL here.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string or an already-parsed list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _normalise_dsn(cls, value: str | None) -> str | None:
        """Accept a libpq DSN and hand back one asyncpg can actually open.

        Managed providers give out `postgresql://...?sslmode=require&channel
        _binding=...`. asyncpg understands neither the bare scheme (SQLAlchemy
        would pick psycopg2) nor libpq-only query parameters, so translate
        rather than making every deployment edit the string by hand.

        Applied to the test DSN as well: a pooled test database would break
        the LISTEN/NOTIFY tests specifically, and they are the ones whose
        failure is least obviously a configuration problem.
        """
        if value is None:
            return None
        parts = urlsplit(value)

        # Refuse a pooled endpoint outright. Correcting it here would be worse
        # than failing: the deployment would work, and Phase 5 would not.
        host = (parts.hostname or "").lower()
        for marker in _POOLED_HOST_MARKERS:
            if marker in host:
                raise ValueError(
                    _POOLED_DSN_ERROR.format(reason=f"host contains {marker!r}")
                )
        if parts.port in _POOLED_PORTS:
            raise ValueError(
                _POOLED_DSN_ERROR.format(reason=f"port is {parts.port}")
            )

        scheme = parts.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+asyncpg"

        query: list[tuple[str, str]] = []
        for key, item in parse_qsl(parts.query, keep_blank_values=True):
            if key == "sslmode":
                query.append(("ssl", _SSLMODE_TO_ASYNCPG.get(item, "require")))
            elif key in ("channel_binding", "options", "application_name"):
                # libpq-only; asyncpg raises TypeError on unknown kwargs.
                continue
            else:
                query.append((key, item))

        return urlunsplit(
            (scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    @model_validator(mode="after")
    def _require_real_secrets(self) -> "Settings":
        """Refuse to exist without real signing keys.

        Deliberately UNCONDITIONAL -- not scoped to ENVIRONMENT. Scoping it
        would mean local development and CI never execute this path, so the
        first time it ran would be the deployment it was written to protect,
        which is the one place a surprise is unaffordable. A default signing
        key has no legitimate use anywhere, local included.

        Raising here means the process cannot start: `settings` is built at
        import time, so a misconfigured deployment fails loudly at boot
        rather than serving forgeable tokens.
        """
        for name, value in (
            ("JWT_SECRET", self.jwt_secret),
            ("QR_SECRET", self.qr_secret),
        ):
            cleaned = (value or "").strip()
            if not cleaned:
                problem = "not set" if value is None else "empty"
            elif cleaned.lower() in _PLACEHOLDER_SECRETS:
                problem = f"still the placeholder value {cleaned!r}"
            elif len(cleaned) < _MIN_SECRET_LENGTH:
                problem = (
                    f"only {len(cleaned)} characters long "
                    f"(minimum {_MIN_SECRET_LENGTH})"
                )
            else:
                continue

            raise ValueError(
                _MISSING_SECRET_ERROR.format(
                    name=name,
                    problem=problem,
                    consequence=_SECRET_CONSEQUENCE[name],
                )
            )
        return self

    @property
    def db_host(self) -> str:
        """Resolved database host, safe to log -- carries no credentials."""
        parts = urlsplit(self.database_url)
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.hostname or '?'}{port}"

    @property
    def db_is_pooled(self) -> bool:
        """Belt-and-braces re-check of what the validator already refused."""
        parts = urlsplit(self.database_url)
        host = (parts.hostname or "").lower()
        return any(m in host for m in _POOLED_HOST_MARKERS) or (
            parts.port in _POOLED_PORTS
        )

    @property
    def sync_database_url(self) -> str:
        """psycopg-flavoured DSN, for tooling that cannot speak asyncpg."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
