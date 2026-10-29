"""Exercises the real migrations in `store/migrations/` against a fresh
in-memory database — not the synthetic fixtures in `test_migrate.py`,
which test the runner mechanics. A migration only ever runs once in
production, which is exactly why it must run in every test session: nothing
else will ever re-verify it applies cleanly.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.store.mappers import (
    assertion_from_row,
    assertion_ruling_from_row,
    assertion_ruling_to_row,
    assertion_to_row,
    company_from_row,
    company_to_row,
    comparison_to_row,
    dimension_digest_to_row,
    intake_queue_item_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.store.migrate import apply_migrations
from screen.types import (
    Assertion,
    AssertionRuling,
    Citation,
    Company,
    Comparison,
    DimensionDigest,
    IntakeQueueItem,
    Opening,
)
from tests.helpers import canned_assertion

_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "src" / "screen" / "store" / "migrations"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn, _MIGRATIONS_DIR)
    return conn


def test_all_migration_files_apply_cleanly_to_a_fresh_database() -> None:
    conn = _connect()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "companies",
        "openings",
        "assertions",
        "assertion_rulings",
        "dimension_rulings",
        "schema_migrations",
    } <= tables


def test_company_insert_and_select_round_trips_through_the_real_schema() -> None:
    conn = _connect()
    company = Company(id="acme", name="Acme Corp", created_at=datetime.now(UTC))
    conn.execute(
        "INSERT INTO companies (id, name, created_at) VALUES (:id, :name, :created_at)",
        company_to_row(company),
    )
    row = conn.execute("SELECT * FROM companies WHERE id = 'acme'").fetchone()
    assert company_from_row(dict(row)) == company


def test_opening_insert_and_select_round_trips_through_the_real_schema() -> None:
    conn = _connect()
    opening = Opening(
        id="acme--eng-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=datetime.now(UTC),
    )
    conn.execute(
        """INSERT INTO openings
               (id, company_id, title, url, research_trace_id,
                created_at, stage)
           VALUES
               (:id, :company_id, :title, :url, :research_trace_id,
                :created_at, :stage)""",
        opening_to_row(opening),
    )
    row = conn.execute("SELECT * FROM openings WHERE id = 'acme--eng-abc123'").fetchone()
    assert opening_from_row(dict(row)) == opening
    assert row["stage"] == "screening"


def test_assertion_insert_and_select_round_trips_through_the_real_schema() -> None:
    conn = _connect()
    citation = Citation(
        url="https://example.com/jobs/1",
        quote="Build and own the platform.",
        host="example.com",
        source_provenance="official",
        independent=True,
        source_date=None,
    )
    assertion = Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="10+ years in platform engineering.",
        citations=[citation],
        created_at=datetime.now(UTC),
    )
    row = assertion_to_row(assertion, opening_id="acme--eng-abc123")
    conn.execute(
        """INSERT INTO assertions
           (id, opening_id, target, fit, provenance, chunk, citations, created_at)
           VALUES (:id, :opening_id, :target, :fit, :provenance, :chunk, :citations, :created_at)""",
        row,
    )
    fetched = conn.execute(
        "SELECT * FROM assertions WHERE id = :id", {"id": assertion.id}
    ).fetchone()
    fetched_assertion = assertion_from_row(dict(fetched))
    assert fetched_assertion is not None
    assert fetched_assertion == assertion


def test_assertion_ruling_insert_and_select_round_trips_through_the_real_schema() -> None:
    conn = _connect()
    ruling = AssertionRuling(
        assertion_id="00000000-0000-0000-0000-000000000001",
        fit="Strong",
        created_at=datetime.now(UTC),
    )
    row = assertion_ruling_to_row(ruling)
    conn.execute(
        """INSERT INTO assertion_rulings (id, assertion_id, fit, created_at)
           VALUES (:id, :assertion_id, :fit, :created_at)""",
        row,
    )
    fetched = conn.execute(
        "SELECT * FROM assertion_rulings WHERE id = :id", {"id": ruling.id}
    ).fetchone()
    assert assertion_ruling_from_row(dict(fetched)) == ruling


_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

_MAPPED_ROWS: dict[str, dict[str, object]] = {
    "companies": company_to_row(Company(id="acme", name="Acme Corp", created_at=_NOW)),
    "openings": opening_to_row(
        Opening(
            id="acme--eng",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/jobs/1",
            research_trace_id="tx0123456789abcdef",
            created_at=_NOW,
        )
    ),
    "assertions": assertion_to_row(canned_assertion(), opening_id="acme--eng"),
    "assertion_rulings": assertion_ruling_to_row(
        AssertionRuling(assertion_id="a1", fit="Strong", created_at=_NOW)
    ),
    "dimension_digests": dimension_digest_to_row(
        DimensionDigest(
            opening_id="acme--eng",
            target="craft_direction",
            digest="Summary.",
            assertion_count=1,
            computed_at=_NOW,
        )
    ),
    "comparisons": comparison_to_row(
        Comparison(
            opening_a_id="a",
            opening_b_id="b",
            target="craft_direction",
            outcome="a",
            predicted_a_beats_b=0.5,
            created_at=_NOW,
        )
    ),
    "intake_queue": intake_queue_item_to_row(
        IntakeQueueItem(id="q1", url="https://example.com/jobs/1", created_at=_NOW)
    ),
}

# `schema_migrations` belongs to the runner; `dimension_rulings` is a retired table
# that nothing reads or writes, kept so the operator's live DB needs no drop migration.
_UNMAPPED_TABLES = {"schema_migrations", "dimension_rulings"}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize("table", sorted(_MAPPED_ROWS))
def test_to_row_mapper_produces_exactly_its_tables_columns(table: str) -> None:
    """A column a migration adds but the mapper omits would silently store its default."""
    assert set(_MAPPED_ROWS[table]) == _columns(_connect(), table)


def test_every_table_has_a_mapper_or_is_explicitly_unmapped() -> None:
    conn = _connect()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == set(_MAPPED_ROWS) | _UNMAPPED_TABLES
