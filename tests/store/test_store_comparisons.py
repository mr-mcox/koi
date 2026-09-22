"""Tests for the append-only `comparisons` repo functions."""

from datetime import UTC, datetime
from pathlib import Path

from screen.store.db import connect
from screen.store.repo import (
    append_comparison,
    comparisons_for_target,
    upsert_company,
    upsert_opening,
)
from screen.types import Company, Comparison, Opening

_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _seed_openings(conn) -> None:
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--eng-a",
            company_id="acme",
            title="Staff Engineer A",
            url="https://example.com/jobs/a",
            research_trace_id="tx0123456789abcdef",
            created_at=_NOW,
        ),
    )
    upsert_opening(
        conn,
        Opening(
            id="acme--eng-b",
            company_id="acme",
            title="Staff Engineer B",
            url="https://example.com/jobs/b",
            research_trace_id="tx0123456789abcdea",
            created_at=_NOW,
        ),
    )


def test_comparisons_for_target_returns_empty_when_none_recorded(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed_openings(conn)
    assert comparisons_for_target(conn, "stretch") == []


def test_append_then_read_comparison_round_trips(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed_openings(conn)
    comparison = Comparison(
        opening_a_id="acme--eng-a",
        opening_b_id="acme--eng-b",
        target="stretch",
        outcome="a",
        predicted_a_beats_b=0.75,
        created_at=_NOW,
    )

    append_comparison(conn, comparison)

    assert comparisons_for_target(conn, "stretch") == [comparison]


def test_append_comparison_keeps_full_history_not_latest_only(tmp_path: Path) -> None:
    """Append-only: a second judgment on the same pair/dimension adds a row, it does not
    replace the first."""
    conn = connect(tmp_path / "screen.db")
    _seed_openings(conn)
    first = Comparison(
        opening_a_id="acme--eng-a",
        opening_b_id="acme--eng-b",
        target="stretch",
        outcome="a",
        predicted_a_beats_b=0.75,
        created_at=_NOW,
    )
    second = Comparison(
        opening_a_id="acme--eng-a",
        opening_b_id="acme--eng-b",
        target="stretch",
        outcome="b",
        predicted_a_beats_b=0.25,
        created_at=_NOW,
    )

    append_comparison(conn, first)
    append_comparison(conn, second)

    assert comparisons_for_target(conn, "stretch") == [first, second]


def test_comparisons_for_target_excludes_other_targets(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed_openings(conn)
    append_comparison(
        conn,
        Comparison(
            opening_a_id="acme--eng-a",
            opening_b_id="acme--eng-b",
            target="schematic",
            outcome="tie",
            predicted_a_beats_b=0.5,
            created_at=_NOW,
        ),
    )

    assert comparisons_for_target(conn, "stretch") == []
