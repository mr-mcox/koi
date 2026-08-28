"""Round-trip tests for `screen.store.db.connect` — the one seam that opens
the SQLite file and guarantees migrations are applied before any caller
touches it.
"""

import sqlite3
from pathlib import Path

from screen.store.db import connect


def test_connect_creates_db_file_and_applies_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "screen.db"
    conn = connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"companies", "openings", "assertions"} <= tables
    assert db_path.exists()


def test_connect_returns_row_factory_rows(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    conn.execute(
        "INSERT INTO companies (id, name, created_at) VALUES ('acme', 'Acme', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    row = conn.execute("SELECT * FROM companies WHERE id = 'acme'").fetchone()
    assert dict(row) == {
        "id": "acme",
        "name": "Acme",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_connect_reuses_existing_db_file_without_reapplying_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "screen.db"
    first = connect(db_path)
    first.execute(
        "INSERT INTO companies (id, name, created_at) VALUES ('acme', 'Acme', '2026-01-01T00:00:00+00:00')"
    )
    first.commit()
    first.close()

    second = connect(db_path)
    row = second.execute("SELECT * FROM companies WHERE id = 'acme'").fetchone()
    assert row is not None


def test_connect_enforces_foreign_keys(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    try:
        conn.execute(
            "INSERT INTO openings (id, company_id, title, url, transcript_id, created_at) "
            "VALUES ('op1', 'no-such-company', 'Eng', 'https://x', 'tx1', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "foreign_keys pragma must be on so a dangling company_id is rejected"
