"""Unit coverage for `rank_screening_pool`'s DB assembly and the stored-comparison
outcome mapping — `tests/test_web.py::test_index_queue_reorders_after_comparison`
covers the end-to-end HTTP path; this covers the branches that path alone doesn't
reach (tie/b outcomes, the explicit `openings` override). The comparison pre-screen
orchestration itself (`run_prescreen`) lives in `tests/test_prescreen_engine.py`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.api.pool import _outcome_for_pair, _to_score_comparison, rank_screening_pool
from screen.score.compare import Comparison as ScoreComparison
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
        target="craft_direction",
        outcome=outcome,  # type: ignore[arg-type]
        predicted_a_beats_b=0.5,
        created_at=_NOW,
    )


def test_to_score_comparison_maps_a_b_and_tie() -> None:
    a_wins = _to_score_comparison(_comparison("a"))
    assert (a_wins.winner, a_wins.loser, a_wins.tie, a_wins.provenance) == (
        "a",
        "b",
        False,
        "operator",
    )

    b_wins = _to_score_comparison(_comparison("b"))
    assert (b_wins.winner, b_wins.loser, b_wins.tie, b_wins.provenance) == (
        "b",
        "a",
        False,
        "operator",
    )

    tie = _to_score_comparison(_comparison("tie"))
    assert (tie.winner, tie.loser, tie.tie, tie.provenance) == ("a", "b", True, "operator")


def test_to_score_comparison_carries_provisional_provenance() -> None:
    """A stored provisional-tie row maps to a score-side `Comparison` that still says
    provisional — the fit's per-provenance beta lookup depends on this surviving the hop."""
    provisional = _comparison("a").model_copy(update={"provenance": "provisional"})
    assert _to_score_comparison(provisional).provenance == "provisional"


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


def test_outcome_for_pair_maps_tie_and_each_winner() -> None:
    tie = ScoreComparison(winner="a", loser="b", tie=True, provenance="provisional")
    assert _outcome_for_pair(tie, "a", "b") == "tie"

    a_wins = ScoreComparison(winner="a", loser="b", provenance="provisional")
    assert _outcome_for_pair(a_wins, "a", "b") == "a"

    b_wins = ScoreComparison(winner="b", loser="a", provenance="provisional")
    assert _outcome_for_pair(b_wins, "a", "b") == "b"
