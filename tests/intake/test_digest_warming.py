"""Unit tests for post-pass digest warming — `_run_dispatch` must warm the
digest cache for every target with assertions before the pass is considered
complete."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from screen.digest.fakes import FakeDigester
from screen.intake.pipeline import run_dispatch
from screen.research.actions import StopAction
from screen.research.batch import RunDispatchDeps
from screen.research.fakes import FakePlanner
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    get_dimension_digest,
    upsert_company,
    upsert_opening,
)
from screen.types import Company, Opening
from tests.helpers import canned_assertion


def _seed_opening(conn: sqlite3.Connection) -> None:
    upsert_company(conn, Company(id="co", name="Example Co", created_at=datetime.now(UTC)))
    upsert_opening(
        conn,
        Opening(
            id="opening",
            company_id="co",
            title="Eng",
            url="https://example.com/jobs/42",
            research_trace_id="t1",
            research_turns_budget=5,
            created_at=datetime.now(UTC),
        ),
    )


def test_run_dispatch_warms_digest_cache_for_every_target(tmp_path: Path) -> None:
    """After `dispatch` returns, every target with assertions has a cached digest."""
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)
    assertions = [canned_assertion("stretch"), canned_assertion("mission")]
    append_assertions(conn, assertions, opening_id="opening")
    digester = FakeDigester(["stretch digest", "mission digest"])
    planner = FakePlanner(sequence=[[StopAction(reason="All rubric dimensions addressed.")]])

    run_dispatch(
        conn,
        "opening",
        "https://example.com/jobs/42",
        assertions,
        company_id="co",
        page_content="content",
        company_name="Example Co",
        opening_title="Eng",
        deps=RunDispatchDeps(planner=planner, digester=digester),
    )

    assert digester.calls == 2
    assert get_dimension_digest(conn, "opening", "stretch") is not None
    assert get_dimension_digest(conn, "opening", "mission") is not None
