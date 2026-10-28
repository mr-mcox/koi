"""Assembling and scoring the screening pool.

Two layers, kept in one module because the lower exists only to feed the upper:
`pool_for_screening` is pure glue onto `screen.score` (no I/O, testable against
synthetic assertions), and `rank_screening_pool` is the one place that reads the
DB to build its arguments — so the JSON routes, the HTML routes and the batch
engine never each re-derive `comparisons_by_target`/`companies_by_opening` from
stored rows.

This sits below `api/` and `web/` on purpose: `research/batch.py` ranks the pool
to pick its next opening, and must not import the web layer to do it.
"""

from __future__ import annotations

import sqlite3

from screen.score.compare import Comparison as ScoreComparison
from screen.score.compare import dimension_posteriors
from screen.score.scorer import rank_pool, stats_for_target
from screen.score.types import PoolInput, PoolScoreResult, ScoringConfig
from screen.store.repo import (
    assertion_rulings_for_opening,
    assertions_for_opening,
    comparisons_for_target,
    list_openings,
)
from screen.types import Assertion, AssertionRuling, Fit, Opening
from screen.types import Comparison as StoredComparison


def latest_ruling_by_assertion(
    rulings: list[AssertionRuling],
) -> dict[str, AssertionRuling]:
    """Rulings are append-only — re-rating is expected and noisy in both directions,
    not an error — so keep the most recent one per assertion for scoring. Callers are
    expected to pass rulings ordered by `created_at` ascending; the last write per
    assertion id wins."""
    return {ruling.assertion_id: ruling for ruling in rulings}


def _comparison_priors(
    pool: list[PoolInput], config: ScoringConfig
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Every scoring dimension's assertion-derived mean/variance per opening — the prior
    `fit_pairwise` starts from. Half-width is the Uniform(-hw, hw) support; its
    variance-matched Gaussian counterpart is `(hw / sqrt(3))**2` (scorer.py's own
    correlated-sampling conversion, reused here for consistency)."""
    means: dict[str, dict[str, float]] = {}
    variances: dict[str, dict[str, float]] = {}
    for slug in config.dimension_weights:
        stats = {
            p.opening_id: stats_for_target(p.assertions, config, slug, p.rulings) for p in pool
        }
        means[slug] = {oid: s.mean for oid, s in stats.items()}
        variances[slug] = {oid: (s.half_width / 3**0.5) ** 2 for oid, s in stats.items()}
    return means, variances


def pool_for_screening(
    openings: list[Opening],
    assertions_by_opening: dict[str, list[Assertion]],
    rulings_by_opening: dict[str, dict[str, Fit]],
    config: ScoringConfig,
    *,
    top_k: int | None = None,
    comparisons_by_target: dict[str, list[ScoreComparison]] | None = None,
    companies_by_opening: dict[str, str] | None = None,
) -> PoolScoreResult:
    """Score the live screening pool jointly, pulling each opening's assertions and any
    assertion-level rulings from the caller. `comparisons_by_target`/`companies_by_opening`
    fit a `DimensionPosterior` per dimension
    with a comparison or a same-company pair; every other dimension keeps its ordinary
    assertion-derived prior, unchanged."""
    pool = [
        PoolInput(
            opening_id=o.id,
            assertions=assertions_by_opening.get(o.id, []),
            rulings=rulings_by_opening.get(o.id) or None,
        )
        for o in openings
    ]
    posteriors = None
    if comparisons_by_target is not None and companies_by_opening is not None:
        means, variances = _comparison_priors(pool, config)
        posteriors = dimension_posteriors(
            means, variances, companies_by_opening, comparisons_by_target, config.comparison_beta
        )
    return rank_pool(pool, config, top_k=top_k, posteriors=posteriors)


def _to_score_comparison(comparison: StoredComparison) -> ScoreComparison:
    """Map a stored `screen.types.Comparison` (opening_a/opening_b/outcome) onto the pure
    fit's `winner`/`loser`/`tie` shape — the fit only ever needs the resolved judgment, and
    `provenance` rides along so the fit can pick this comparison's beta. Digest versions
    carry over so `_settled_pairs` can tell whether the evidence shown at judgment time is
    still current."""
    if comparison.outcome == "tie":
        return ScoreComparison(
            winner=comparison.opening_a_id,
            loser=comparison.opening_b_id,
            tie=True,
            provenance=comparison.provenance,
            winner_digest_version=comparison.opening_a_digest_version,
            loser_digest_version=comparison.opening_b_digest_version,
        )
    if comparison.outcome == "a":
        return ScoreComparison(
            winner=comparison.opening_a_id,
            loser=comparison.opening_b_id,
            provenance=comparison.provenance,
            winner_digest_version=comparison.opening_a_digest_version,
            loser_digest_version=comparison.opening_b_digest_version,
        )
    return ScoreComparison(
        winner=comparison.opening_b_id,
        loser=comparison.opening_a_id,
        provenance=comparison.provenance,
        winner_digest_version=comparison.opening_b_digest_version,
        loser_digest_version=comparison.opening_a_digest_version,
    )


def screening_pool_inputs(
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
    ) = screening_pool_inputs(conn, config, openings=openings)
    return pool_for_screening(
        openings,
        assertions_by_opening,
        rulings_by_opening,
        config,
        comparisons_by_target=comparisons_by_target,
        companies_by_opening=companies_by_opening,
    )
