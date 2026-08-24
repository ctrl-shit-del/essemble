"""The seed script's guards and its screen specifications.

Nothing here touches the database. The parts of scripts/seed.py worth testing
are the ones that are dangerous (the --reset host guard) or that would fail
only at run time against a real database (a screen spec whose category rows do
not cover the hall).
"""

import pytest

from scripts import seed


# ------------------------------------------------------------- reset guard


@pytest.mark.parametrize("host", sorted(seed.LOCAL_HOSTS))
def test_reset_is_allowed_on_a_local_host(host, monkeypatch):
    # An IPv6 literal only parses as a host when bracketed, which is how a
    # real DSN would carry it.
    literal = f"[{host}]" if ":" in host else host
    monkeypatch.setattr(
        seed.settings, "database_url", f"postgresql+asyncpg://u:p@{literal}:5432/db"
    )
    allowed, _reason = seed.reset_is_allowed(force=False)
    assert allowed is True


def test_reset_is_refused_when_the_host_cannot_be_parsed(monkeypatch):
    """An unparseable DSN must fail closed, not open."""
    monkeypatch.setattr(seed.settings, "database_url", "not-a-url")
    allowed, _reason = seed.reset_is_allowed(force=False)
    assert allowed is False


REMOTE = "postgresql+asyncpg://u:p@ep-something.aws.neon.tech/db?ssl=require"


def test_reset_is_refused_on_a_remote_host(monkeypatch):
    """The whole point of the guard.

    This script is expected to sit next to a hosted demo database, where a
    stray --reset is unrecoverable.
    """
    monkeypatch.setattr(seed.settings, "database_url", REMOTE)
    allowed, reason = seed.reset_is_allowed(force=False)
    assert allowed is False
    assert "neon.tech" in reason


def test_reset_on_a_remote_host_needs_the_explicit_flag(monkeypatch):
    monkeypatch.setattr(seed.settings, "database_url", REMOTE)
    allowed, reason = seed.reset_is_allowed(force=True)
    assert allowed is True
    assert "overridden" in reason


def test_reset_never_truncates_the_migration_table():
    """Wiping data must not look like un-migrating."""
    assert "alembic_version" not in seed.APPLICATION_TABLES


# ------------------------------------------------------------ screen specs


SPECS = [
    seed.LARGE_12x18,
    seed.LARGE_10x14,
    seed.SMALL_8x12,
    seed.LUXE_10x14,
    seed.LUXE_8x12,
]


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_every_screen_spec_generates_a_complete_layout(spec):
    """Run the real generator over each spec.

    A category range that misses a row, or two categories claiming the same
    row, raises here rather than half way through a seed run.
    """
    from app.schemas.venue import LayoutCategory

    seats = seed.generate_seats(
        spec.rows,
        spec.seats_per_row,
        spec.aisles,
        [
            LayoutCategory(name=n, rank=r, row_from=f, row_to=t)
            for n, r, f, t in spec.categories
        ],
    )
    assert len(seats) == spec.rows * spec.seats_per_row
    assert {s.category_name for s in seats} == {c[0] for c in spec.categories}


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_every_screen_spec_is_priced(spec):
    """A category with no price would make its show unbookable."""
    prices = set(seed.PRICING) | set(seed.LUXE_PRICING)
    missing = {name for name, _r, _f, _t in spec.categories} - prices
    assert missing == set()


def test_the_two_large_screens_have_three_categories_and_the_small_ones_two():
    assert len(seed.LARGE_12x18.categories) == 3
    assert len(seed.LARGE_10x14.categories) == 3
    assert len(seed.LUXE_10x14.categories) == 3
    assert len(seed.SMALL_8x12.categories) == 2
    assert len(seed.LUXE_8x12.categories) == 2


# ---------------------------------------------------------------- catalog


def test_every_event_carries_artwork_and_type_specific_fields():
    """The frontend needs a poster; the API refuses some combinations."""
    for spec in seed.EVENTS:
        assert seed.poster(spec.slug).startswith("https://")
        assert seed.backdrop(spec.slug).startswith("https://")
        if spec.event_type is seed.EventType.MOVIE:
            assert spec.runtime_min, f"{spec.title}: a movie needs a runtime"
            assert spec.certification, f"{spec.title}: a movie needs a certification"
        else:
            assert spec.artist_name, f"{spec.title}: a live event needs an artist"


def test_the_seeded_history_covers_the_genres_the_recommender_reads():
    """4 sci-fi, 2 action, 3 stand-up, per the demo brief."""
    by_slug = {spec.slug: spec for spec in seed.EVENTS}
    assert "Sci-Fi" in by_slug["nebula-drift"].genres
    assert "Sci-Fi" in by_slug["quantum-hour"].genres
    assert "Action" in by_slug["kaaval-nagaram"].genres
    assert "Stand-Up" in by_slug["under-review"].genres
