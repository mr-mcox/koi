"""Backend-only pair/dimension picker for operator pairwise comparisons.
`select_comparison` scores every candidate `(opening, opening, dimension)` triple as
`closeness_overall × boundary_weight × sqrt(weight_d) × var_diff_d × jitter`
(picker-variance-share.md, its Amendment). `closeness_overall` and `boundary_weight`
identify a pair whose overall rank is both genuinely contested and near the top-K
boundary — both use the full rubric weight (squared, since dimensions are independent),
because that's the real weighted rollup. `sqrt(weight_d)` and `var_diff_d` then choose
which dimension to ask about *within* that pair: dimension choice deliberately uses a
gentler weight exponent than pair choice, because "is this pair's rank in doubt"
legitimately scales with the full rubric weight but "what do I know least about here"
should not — any exponent ≥ 1 there let the highest-weight dimension dominate
regardless of how little of it was left to learn, confirmed against live data. A small
log-normal jitter keeps one comparison result from permanently sinking a pair's
priority. It never asks about a dimension where either side has no assertions —
`domain` included.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from screen.score.bandit import boundary_weight
from screen.score.compare import COMPANY_LEVEL_TARGETS, Comparison, fit_pairwise
from screen.score.scorer import stats_for_target
from screen.score.types import ScoringConfig
from screen.types import Assertion, Fit

_MIN_PAIR = 2


@dataclass(frozen=True)
class ComparisonSuggestion:
    """A single pair/dimension the operator should compare next."""

    target: str
    opening_a_id: str
    opening_b_id: str


def _p_a_gt_b(mean_diff: float, variance_diff: float) -> float:
    """P(X_a > X_b) for X_a - X_b ~ N(mean_diff, variance_diff)."""
    if variance_diff <= 0.0:
        if mean_diff > 0.0:
            return 1.0
        if mean_diff < 0.0:
            return 0.0
        return 0.5
    return 0.5 * (1.0 + math.erf(mean_diff / math.sqrt(2.0 * variance_diff)))


def _qualify_for_dimension(
    target: str,
    opening_ids: list[str],
    assertions_by_opening: dict[str, list[Assertion]],
    rulings_by_opening: dict[str, dict[str, Fit]] | None,
    config: ScoringConfig,
) -> list[str]:
    """Openings that may participate in a comparison on `target`. Every dimension,
    including `domain`, requires at least one effective assertion — the research
    dispatcher already covers `domain` on the same uncertainty-ranked footing as every
    other target (`all_dimension_slugs()` feeds `LoopState.targets`), so there is no
    dimension that structurally lacks evidence to special-case around."""
    qualified: list[str] = []
    for oid in opening_ids:
        stats = stats_for_target(
            assertions_by_opening.get(oid, []),
            config,
            target,
            rulings_by_opening.get(oid) if rulings_by_opening else None,
        )
        if stats.n > 0.0:
            qualified.append(oid)
    return qualified


def _auto_ties(
    target: str,
    qualified_ids: list[str],
    companies_by_opening: dict[str, str],
) -> list[Comparison]:
    """Generated tie terms for same-company pairs on company-level dimensions."""
    if target not in COMPANY_LEVEL_TARGETS:
        return []
    by_company: dict[str, list[str]] = {}
    for oid in qualified_ids:
        by_company.setdefault(companies_by_opening[oid], []).append(oid)
    return [
        Comparison(winner=a, loser=b, tie=True)
        for ids in by_company.values()
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
    ]


def _prior_variance(
    target: str,
    opening_id: str,
    assertions_by_opening: dict[str, list[Assertion]],
    rulings_by_opening: dict[str, dict[str, Fit]] | None,
    config: ScoringConfig,
) -> float:
    """An opening's prior variance on `target`, before any comparison evidence."""
    stats = stats_for_target(
        assertions_by_opening.get(opening_id, []),
        config,
        target,
        rulings_by_opening.get(opening_id) if rulings_by_opening else None,
    )
    return (stats.half_width / 3.0**0.5) ** 2


_DimensionPosterior = tuple[dict[str, float], dict[str, dict[str, float]]]


def _dimension_posterior(
    target: str,
    opening_ids: list[str],
    *,
    assertions_by_opening: dict[str, list[Assertion]],
    rulings_by_opening: dict[str, dict[str, Fit]] | None,
    comparisons: list[Comparison],
    companies_by_opening: dict[str, str],
    config: ScoringConfig,
) -> _DimensionPosterior:
    """Fit one dimension's posterior over *every* opening in the pool, not only the ones
    with evidence — an opening with no assertions on `target` enters at its unexamined prior
    (mean 0, matching `Uniform(-1, +1)`'s variance), the same prior `rank_pool` gives it.
    Comparisons only move openings they reference; every other opening keeps its
    independent prior with no cross-opening covariance. Returns `(means, covariance)` as
    nested dicts keyed by opening id, used both for the overall per-pair variance (every
    dimension contributes, evidenced or not) and, for qualified pairs, the dimension's own
    contribution."""
    prior_means: dict[str, float] = {}
    prior_variances: dict[str, float] = {}
    for oid in opening_ids:
        stats = stats_for_target(
            assertions_by_opening.get(oid, []),
            config,
            target,
            rulings_by_opening.get(oid) if rulings_by_opening else None,
        )
        prior_means[oid] = stats.mean
        prior_variances[oid] = (stats.half_width / 3.0**0.5) ** 2
    relevant = [c for c in comparisons if c.winner in prior_means and c.loser in prior_means]
    means, covariance = fit_pairwise(
        prior_means,
        prior_variances,
        relevant + _auto_ties(target, opening_ids, companies_by_opening),
        config.comparison_beta,
    )
    cov_by_id = {
        a: {b: covariance[i, j] for j, b in enumerate(opening_ids)}
        for i, a in enumerate(opening_ids)
    }
    return {oid: means[i] for i, oid in enumerate(opening_ids)}, cov_by_id


def _overall_diff(
    a: str,
    b: str,
    posteriors: dict[str, _DimensionPosterior],
    config: ScoringConfig,
) -> tuple[float, float]:
    """The weighted-rollup score difference between two openings: mean and variance summed
    across every configured dimension, each dimension's contribution scaled by its rubric
    weight (variance by weight squared, since dimensions are independent). Dividing by
    `total_weight` would rescale both mean and variance identically and cancel out of
    `_p_a_gt_b`, so it's skipped."""
    mean_diff = 0.0
    var_diff = 0.0
    for target, weight in config.dimension_weights.items():
        means, covariance = posteriors[target]
        mean_diff += weight * (means[a] - means[b])
        var_diff += (weight**2) * (covariance[a][a] + covariance[b][b] - 2.0 * covariance[a][b])
    return mean_diff, var_diff


def _best_dimension_for_pair(
    a: str,
    b: str,
    pair_priority: float,
    *,
    companies_by_opening: dict[str, str],
    posteriors: dict[str, _DimensionPosterior],
    qualified_by_dimension: dict[str, set[str]],
    config: ScoringConfig,
) -> tuple[float, str] | None:
    """The dimension contributing most variance to one pair's contest, scaled by
    `sqrt(weight)` (a gentler exponent than the pair-priority calculation uses — see
    module docstring) and the pair's priority (overall closeness × boundary proximity)."""
    best_score = -1.0
    best_target: str | None = None
    for target, weight in config.dimension_weights.items():
        qualified = qualified_by_dimension[target]
        if a not in qualified or b not in qualified:
            continue
        if target in COMPANY_LEVEL_TARGETS and companies_by_opening[a] == companies_by_opening[b]:
            continue
        _, covariance = posteriors[target]
        dim_var_diff = covariance[a][a] + covariance[b][b] - 2.0 * covariance[a][b]
        score = pair_priority * math.sqrt(weight) * dim_var_diff
        if score > best_score:
            best_score = score
            best_target = target
    return (best_score, best_target) if best_target is not None else None


def _best_triple(
    opening_ids: list[str],
    companies_by_opening: dict[str, str],
    posteriors: dict[str, _DimensionPosterior],
    qualified_by_dimension: dict[str, set[str]],
    p_top_k_by_opening: dict[str, float],
    *,
    config: ScoringConfig,
    rng: np.random.Generator,
    gate_on_boundary: bool,
) -> tuple[float, ComparisonSuggestion] | None:
    """The `(pair, dimension)` with the highest jittered priority. A pair's priority is
    `closeness_overall × boundary_weight(max(p_top_k))` — both use the full rubric weight
    (via `_overall_diff`), because they measure the real weighted rollup and its relevance
    to the top-K cutoff; a pair where neither opening could plausibly enter or leave top-K
    scores near zero regardless of how contested the two openings are against each other.
    `gate_on_boundary=False` skips that factor entirely (score is `closeness` alone) —
    when the whole pool fits within top-K, every opening's `p_top_k` is trivially 1.0 and
    `boundary_weight` would zero out every candidate even though relative order inside a
    small pool is still exactly what the operator is judging. Within a qualifying pair,
    `_best_dimension_for_pair` picks the dimension; jitter is applied once per triple,
    after both choices, so it can't make a boundary-irrelevant pair suddenly worth asking
    about."""
    best_score = -1.0
    best: ComparisonSuggestion | None = None
    for i, a in enumerate(opening_ids):
        for b in opening_ids[i + 1 :]:
            mean_diff, var_diff = _overall_diff(a, b, posteriors, config)
            closeness = 0.5 - abs(_p_a_gt_b(mean_diff, var_diff) - 0.5)
            if closeness <= 0.0:
                continue
            boundary = (
                max(boundary_weight(p_top_k_by_opening[a]), boundary_weight(p_top_k_by_opening[b]))
                if gate_on_boundary
                else 1.0
            )
            pair_priority = closeness * boundary
            if pair_priority <= 0.0:
                continue
            dimension_choice = _best_dimension_for_pair(
                a,
                b,
                pair_priority,
                companies_by_opening=companies_by_opening,
                posteriors=posteriors,
                qualified_by_dimension=qualified_by_dimension,
                config=config,
            )
            if dimension_choice is None:
                continue
            score, target = dimension_choice
            jittered = score * math.exp(rng.normal(0.0, config.comparison_jitter_sigma))
            if jittered > best_score:
                best_score = jittered
                best = ComparisonSuggestion(target=target, opening_a_id=a, opening_b_id=b)
    return (best_score, best) if best is not None else None


def select_comparison(
    opening_ids: list[str],
    companies_by_opening: dict[str, str],
    assertions_by_opening: dict[str, list[Assertion]],
    comparisons_by_target: dict[str, list[Comparison]],
    p_top_k_by_opening: dict[str, float],
    *,
    config: ScoringConfig,
    rulings_by_opening: dict[str, dict[str, Fit]] | None = None,
    rng: np.random.Generator | None = None,
) -> ComparisonSuggestion | None:
    """Return the most useful comparison opportunity, or `None` if none qualifies.
    Every dimension is fit over the whole pool (unexamined openings enter at their
    unexamined prior, exactly as `rank_pool` treats them) so the overall weighted-rollup
    score difference between any two openings can be computed. A pair's priority is how
    close that overall contest is (`closeness`) times how much either side's top-K
    membership could still move (`boundary_weight`, from `p_top_k_by_opening` — typically
    `PoolScoreResult.opening_ranks[*].p_top_k`) — a pair neither side of which can
    plausibly reach or leave top-K scores near zero regardless of closeness, *unless* the
    whole pool is at or under `top_k`, where every opening's `p_top_k` is trivially 1.0
    and the boundary factor is skipped rather than zeroing out every candidate. Within a
    qualifying pair, the dimension asked is the one contributing the most variance to
    that contest, scaled by `sqrt(weight)` (module docstring explains why not `weight`
    itself), restricted to dimensions where both openings have at least one assertion
    (`domain` included — no structural exemption) and excluding same-company pairs on
    company-level dimensions (auto-tied instead). A small log-normal jitter is applied to
    each candidate's final score so a single judgment can't permanently sink a pair's
    priority; `rng` defaults to a fresh unseeded generator (the picker doesn't need
    run-to-run reproducibility the way `rank_pool` does), but callers wanting determinism
    (tests, calibration replay) can pass their own.
    """
    if len(opening_ids) < _MIN_PAIR:
        return None
    rng = rng if rng is not None else np.random.default_rng()
    posteriors: dict[str, _DimensionPosterior] = {}
    qualified_by_dimension: dict[str, set[str]] = {}
    for target in config.dimension_weights:
        qualified_by_dimension[target] = set(
            _qualify_for_dimension(
                target, opening_ids, assertions_by_opening, rulings_by_opening, config
            )
        )
        posteriors[target] = _dimension_posterior(
            target,
            opening_ids,
            assertions_by_opening=assertions_by_opening,
            rulings_by_opening=rulings_by_opening,
            comparisons=list(comparisons_by_target.get(target, [])),
            companies_by_opening=companies_by_opening,
            config=config,
        )
    result = _best_triple(
        opening_ids,
        companies_by_opening,
        posteriors,
        qualified_by_dimension,
        p_top_k_by_opening,
        config=config,
        rng=rng,
        gate_on_boundary=len(opening_ids) > config.top_k,
    )
    return result[1] if result is not None else None
