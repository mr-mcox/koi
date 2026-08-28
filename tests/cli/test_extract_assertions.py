"""Unit tests for `_extract_assertions` — extract-and-persist, called directly."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from screen.extract.fakes import FakeExtractor
from screen.intake.cli import _extract_assertions
from screen.store.db import connect
from screen.store.repo import assertions_for_opening, upsert_company, upsert_opening
from screen.types import Company, Opening
from tests.cli.helpers import canned_assertion


def _seed_opening(conn: sqlite3.Connection) -> None:
    upsert_company(conn, Company(id="co", name="Example Co", created_at=datetime.now(UTC)))
    upsert_opening(
        conn,
        Opening(
            id="opening",
            company_id="co",
            title="Eng",
            url="https://example.com/jobs/42",
            transcript_id="t1",
            created_at=datetime.now(UTC),
        ),
    )


def test_extract_assertions_appends_not_truncates(tmp_path: Path) -> None:
    """_extract_assertions is append-only: a second call appends, not replaces (Wall 6)."""
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)

    fake_ext = FakeExtractor([[canned_assertion("stretch")], [canned_assertion("peer")]])

    _extract_assertions(conn, "opening", "chunk", extractor=fake_ext)
    _extract_assertions(conn, "opening", "chunk", extractor=fake_ext)

    assertions = assertions_for_opening(conn, "opening")
    assert len(assertions) == 2, (
        f"Expected 2 persisted assertions, got {len(assertions)}. "
        "append_assertions must never truncate existing rows."
    )
    assert assertions[0].target == "stretch"
    assert assertions[1].target == "peer"


def test_extract_assertions_each_result_is_valid_assertion(tmp_path: Path) -> None:
    """Every persisted row must parse as a valid Assertion."""
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)
    fake_ext = FakeExtractor([[canned_assertion("mission"), canned_assertion("domain")]])
    _extract_assertions(conn, "opening", "chunk", extractor=fake_ext)

    assertions = assertions_for_opening(conn, "opening")
    assert len(assertions) == 2
    for a in assertions:
        assert a.provenance == "model_proposed"
        assert len(a.citations) >= 1


def test_extract_assertions_skips_db_write_when_extractor_returns_nothing(
    tmp_path: Path,
) -> None:
    """An empty extraction result must not call append_assertions (no-op branch)."""
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)
    fake_ext = FakeExtractor([[]])

    result = _extract_assertions(conn, "opening", "chunk", extractor=fake_ext)

    assert result == []
    assert assertions_for_opening(conn, "opening") == []
