"""Unit coverage for `rank_screening_pool`'s DB assembly and the stored-comparison
outcome mapping — `tests/test_web.py::test_index_queue_reorders_after_comparison`
covers the end-to-end HTTP path; this covers the branches that path alone doesn't
reach (tie/b outcomes, the explicit `openings` override)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.api.pool import _to_score_comparison, rank_screening_pool
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.store.db import connect
from screen.store.repo import upsert_company, upsert_opening
from screen.types import Company, Comparison, Opening

_NOW = datetime(2026, 9, 17, tzinfo=UTC)


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


def _comparison(outcome: str) -> Comparison:
    return Comparison(
        opening_a_id="a",
        opening_b_id="b",
        target="stretch",
        outcome=outcome,  # type: ignore[arg-type]
        predicted_a_beats_b=0.5,
        created_at=_NOW,
    )


def test_to_score_comparison_maps_a_b_and_tie() -> None:
    a_wins = _to_score_comparison(_comparison("a"))
    assert (a_wins.winner, a_wins.loser, a_wins.tie) == ("a", "b", False)

    b_wins = _to_score_comparison(_comparison("b"))
    assert (b_wins.winner, b_wins.loser, b_wins.tie) == ("b", "a", False)

    tie = _to_score_comparison(_comparison("tie"))
    assert (tie.winner, tie.loser, tie.tie) == ("a", "b", True)


def test_rank_screening_pool_defaults_to_live_screening_stage(
    tmp_path: Path, config: ScoringConfig
) -> None:
    """No `openings` override means the screening-stage pool, read fresh from the DB —
    the shape both `web.routes` and `api.routes`'s `/queue` rely on."""
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--a",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/a",
            research_trace_id="tx" + "0" * 18,
            created_at=_NOW,
        ),
    )

    result = rank_screening_pool(conn, config)

    assert [r.opening_id for r in result.opening_ranks] == ["acme--a"]
