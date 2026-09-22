"""Glue between the FastAPI routes and the pure Scorer (`screen.score`).

Routes call `pool_for_screening`, not `rank_pool()` directly — the assembly of
per-opening `PoolInput`s from stored assertions and rulings lives in exactly one
place, and this module has no I/O of its own, so it's testable against synthetic
assertions without a database.
"""

from __future__ import annotations

from screen.score.compare import Comparison, dimension_posteriors
from screen.score.scorer import rank_pool, stats_for_target
from screen.score.types import PoolInput, PoolScoreResult, ScoringConfig
from screen.types import Assertion, AssertionRuling, Fit, Opening


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
    comparisons_by_target: dict[str, list[Comparison]] | None = None,
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
