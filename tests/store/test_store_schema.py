"""Exercises the real migrations in `store/migrations/` against a fresh
in-memory database — not the synthetic fixtures in `test_store_migrate.py`,
which test the runner mechanics. A migration only ever runs once in
production, which is exactly why it must run in every test session: nothing
else will ever re-verify it applies cleanly.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from screen.store.mappers import (
    assertion_from_row,
    assertion_ruling_from_row,
    assertion_ruling_to_row,
    assertion_to_row,
    company_from_row,
    company_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.store.migrate import apply_migrations
from screen.types import Assertion, AssertionRuling, Citation, Company, Opening

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
        """INSERT INTO openings (id, company_id, title, url, research_trace_id, created_at)
           VALUES (:id, :company_id, :title, :url, :research_trace_id, :created_at)""",
        opening_to_row(opening),
    )
    row = conn.execute("SELECT * FROM openings WHERE id = 'acme--eng-abc123'").fetchone()
    assert opening_from_row(dict(row)) == opening


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
        target="stretch",
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
    assert assertion_from_row(dict(fetched)) == assertion


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
