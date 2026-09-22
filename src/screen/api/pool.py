"""The one place that reads the DB to assemble a scored screening pool - both the JSON
and HTML routers call `rank_screening_pool` rather than each re-deriving
`comparisons_by_target`/`companies_by_opening` from stored rows.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from screen.api.scoring import latest_ruling_by_assertion, pool_for_screening
from screen.score.compare import Comparison as ScoreComparison
from screen.score.compare_picker import ComparisonSuggestion, select_comparison
from screen.score.types import PoolScoreResult, ScoringConfig
from screen.store.repo import (
    assertion_rulings_for_opening,
    assertions_for_opening,
    comparisons_for_target,
    list_openings,
)
from screen.types import Assertion, Fit, Opening
from screen.types import Comparison as StoredComparison


def _to_score_comparison(comparison: StoredComparison) -> ScoreComparison:
    """Map a stored `screen.types.Comparison` (opening_a/opening_b/outcome) onto the pure
    fit's `winner`/`loser`/`tie` shape — the fit only ever needs the resolved judgment."""
    if comparison.outcome == "tie":
        return ScoreComparison(
            winner=comparison.opening_a_id, loser=comparison.opening_b_id, tie=True
        )
    if comparison.outcome == "a":
        return ScoreComparison(winner=comparison.opening_a_id, loser=comparison.opening_b_id)
    return ScoreComparison(winner=comparison.opening_b_id, loser=comparison.opening_a_id)


def _screening_pool_inputs(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    openings: list[Opening] | None = None,
) -> tuple[
    list[Opening],
    dict[str, list[Assertion]],
    dict[str, dict[str, Fit]],
    dict[str, list[ScoreComparison]],
    dict[str, str],
]:
    """Collect the raw inputs the pool scorer and comparison picker both need."""
    openings = openings if openings is not None else list_openings(conn, stage="screening")
    assertions_by_opening = {o.id: assertions_for_opening(conn, o.id) for o in openings}
    rulings_by_opening: dict[str, dict[str, Fit]] = {
        o.id: {
            ruling.assertion_id: ruling.fit
            for ruling in latest_ruling_by_assertion(
                assertion_rulings_for_opening(conn, o.id)
            ).values()
        }
        for o in openings
    }
    comparisons_by_target = {
        target: [_to_score_comparison(c) for c in comparisons_for_target(conn, target)]
        for target in config.dimension_weights
    }
    companies_by_opening = {o.id: o.company_id for o in openings}
    return (
        openings,
        assertions_by_opening,
        rulings_by_opening,
        comparisons_by_target,
        companies_by_opening,
    )


def rank_screening_pool(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    openings: list[Opening] | None = None,
) -> PoolScoreResult:
    """All screening openings scored jointly with their assertion-level rulings and any
    stored comparisons — every dimension with a comparison or a same-company pair gets
    a comparison-fitted posterior instead of its ordinary assertion-derived prior.
    `openings` defaults to the live screening stage; a caller that needs one opening
    included regardless of its stage (the single-opening score route) passes its own
    union."""
    (
        openings,
        assertions_by_opening,
        rulings_by_opening,
        comparisons_by_target,
        companies_by_opening,
    ) = _screening_pool_inputs(conn, config, openings=openings)
    return pool_for_screening(
        openings,
        assertions_by_opening,
        rulings_by_opening,
        config,
        comparisons_by_target=comparisons_by_target,
        companies_by_opening=companies_by_opening,
    )


def suggest_next_comparison(
    conn: sqlite3.Connection,
    config: ScoringConfig,
) -> ComparisonSuggestion | None:
    """Pick the most useful pair/dimension for the operator to compare next."""
    (
        openings,
        assertions_by_opening,
        rulings_by_opening,
        comparisons_by_target,
        companies_by_opening,
    ) = _screening_pool_inputs(conn, config)
    pool_result = rank_screening_pool(conn, config, openings=openings)
    p_top_k_by_opening = {r.opening_id: r.p_top_k for r in pool_result.opening_ranks}
    return select_comparison(
        [o.id for o in openings],
        companies_by_opening,
        assertions_by_opening,
        comparisons_by_target,
        p_top_k_by_opening,
        config=config,
        rulings_by_opening=rulings_by_opening,
        rng=np.random.default_rng(config.seed),
    )
