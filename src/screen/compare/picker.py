"""Backend-only pair/dimension picker for operator pairwise comparisons.

`select_comparison` skips pairs whose overall outcome is already settled (judged on the
full weighted rollup, `_overall_diff`), prioritizes the rest by how much either side's
top-K membership could still move (`boundary_weight`), and within a pair asks about the
dimension contributing the most variance, scaled by `sqrt(weight)`. Dimension choice
deliberately uses a gentler weight exponent than the rollup: "is this pair's rank in
doubt" legitimately scales with the full rubric weight, but "what do I know least about
here" should not — any exponent ≥ 1 there let the highest-weight dimension dominate
regardless of how little of it was left to learn, confirmed against live data. A
log-normal jitter keeps one comparison result from permanently sinking a pair's
priority. It never asks about a dimension where either side has no assertions —
`domain` included.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from screen.score.bandit import boundary_weight
from screen.score.pairwise import COMPANY_LEVEL_TARGETS, Comparison, fit_pairwise
from screen.score.scorer import stats_for_target
from screen.score.types import ScoringConfig
from screen.types import Assertion, Fit

_MIN_PAIR = 2
_PAIR_SKIP_THRESHOLD = 0.05
"""P(A > B) floor/ceiling: pairs outside [_PAIR_SKIP_THRESHOLD, 1 - _PAIR_SKIP_THRESHOLD]
are skipped before boundary_weight and before reaching Jev, so overwhelmingly decided
pairs don't burn Jev calls. It is an exclusion gate, not a multiplier: a
strong-vs-unknown pair still passes as long as its overall uncertainty spans the band."""


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


def _settled_pairs(
    target: str,
    comparisons: list[Comparison],
    assertions_by_opening: dict[str, list[Assertion]],
) -> set[frozenset[str]]:
    """Pairs whose *latest* comparison on this dimension is either provisional (hard-excluded),
    or an operator ruling where the underlying digest versions haven't changed."""
    latest_comparison: dict[frozenset[str], Comparison] = {}
    for c in comparisons:
        latest_comparison[frozenset({c.winner, c.loser})] = c

    settled = set()
    for pair, c in latest_comparison.items():
        if c.provenance == "provisional":
            settled.add(pair)
            continue

        # For operator rulings, check if new evidence arrived since the judgment
        count_winner = str(
            sum(1 for a in assertions_by_opening.get(c.winner, []) if a.target == target)
        )
        count_loser = str(
            sum(1 for a in assertions_by_opening.get(c.loser, []) if a.target == target)
        )
        if c.winner_digest_version == count_winner and c.loser_digest_version == count_loser:
            settled.add(pair)

    return settled


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
    provisionally_settled_by_dimension: dict[str, set[frozenset[str]]],
    config: ScoringConfig,
) -> tuple[float, str] | None:
    """The dimension contributing most variance to one pair's contest, scaled by
    `sqrt(weight)` (see module docstring) and the pair's priority.
    A (pair, dimension) whose latest comparison is provisional is hard-excluded, not just
    down-weighted — unlike an operator ruling (which stays askable, variance-decayed),
    the operator has never seen this triple, so there's nothing to re-judge until they
    visit the review surface and override it (which records a later, operator-provenance
    comparison on the same pair, naturally returning it here)."""
    best_score = -1.0
    best_target: str | None = None
    for target, weight in config.dimension_weights.items():
        qualified = qualified_by_dimension[target]
        if a not in qualified or b not in qualified:
            continue
        if target in COMPANY_LEVEL_TARGETS and companies_by_opening[a] == companies_by_opening[b]:
            continue
        if frozenset({a, b}) in provisionally_settled_by_dimension.get(target, set()):
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
    provisionally_settled_by_dimension: dict[str, set[frozenset[str]]],
    p_top_k_by_opening: dict[str, float],
    *,
    config: ScoringConfig,
    rng: np.random.Generator,
    gate_on_boundary: bool,
) -> tuple[float, ComparisonSuggestion] | None:
    """`(pair, dimension)` with the highest jittered priority. A pair's priority is
    `boundary_weight(max(p_top_k))` — pairs where neither opening's top-K membership
    could still move score near zero. Pairs whose overall outcome is already settled are
    skipped first, by `_PAIR_SKIP_THRESHOLD`."""
    best_score = -1.0
    best: ComparisonSuggestion | None = None
    for i, a in enumerate(opening_ids):
        for b in opening_ids[i + 1 :]:
            mean_diff, var_diff = _overall_diff(a, b, posteriors, config)
            p_a_gt_b = _p_a_gt_b(mean_diff, var_diff)
            if p_a_gt_b < _PAIR_SKIP_THRESHOLD or p_a_gt_b > 1.0 - _PAIR_SKIP_THRESHOLD:
                continue
            boundary = (
                max(
                    boundary_weight(p_top_k_by_opening[a], config.boundary_weight_floor),
                    boundary_weight(p_top_k_by_opening[b], config.boundary_weight_floor),
                )
                if gate_on_boundary
                else 1.0
            )
            pair_priority = boundary
            dimension_choice = _best_dimension_for_pair(
                a,
                b,
                pair_priority,
                companies_by_opening=companies_by_opening,
                posteriors=posteriors,
                qualified_by_dimension=qualified_by_dimension,
                provisionally_settled_by_dimension=provisionally_settled_by_dimension,
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
    excluded_triples: set[tuple[frozenset[str], str]] | None = None,
) -> ComparisonSuggestion | None:
    """Return the most useful comparison opportunity, or `None` if none qualifies.
    Every dimension is fit over the whole pool (unexamined openings enter at their
    unexamined prior, exactly as `rank_pool` treats them) so the overall weighted-rollup
    score difference between any two openings can be computed. `p_top_k_by_opening`
    feeds `boundary_weight`, except when the whole pool is at or under `top_k`: every
    `p_top_k` is then trivially 1.0, and the boundary factor is skipped. Same-company
    pairs on company-level dimensions are never asked (they are auto-tied). `rng`
    defaults to a fresh unseeded generator (the picker doesn't need run-to-run
    reproducibility the way `rank_pool` does), but callers wanting determinism (tests,
    calibration replay) can pass their own. `excluded_triples` removes specific
    (unordered pair, dimension) triples from the menu for this call only, without
    recording anything — the speculative pre-screen uses it to answer "what would come
    next" while the operator is still deciding the triple in front of them.
    """
    if len(opening_ids) < _MIN_PAIR:
        return None
    rng = rng if rng is not None else np.random.default_rng()
    posteriors: dict[str, _DimensionPosterior] = {}
    qualified_by_dimension: dict[str, set[str]] = {}
    provisionally_settled_by_dimension: dict[str, set[frozenset[str]]] = {}
    for target in config.dimension_weights:
        qualified_by_dimension[target] = set(
            _qualify_for_dimension(
                target, opening_ids, assertions_by_opening, rulings_by_opening, config
            )
        )
        provisionally_settled_by_dimension[target] = _settled_pairs(
            target, comparisons_by_target.get(target, []), assertions_by_opening
        ) | {
            pair
            for pair, excluded_target in (excluded_triples or set())
            if excluded_target == target
        }
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
        provisionally_settled_by_dimension,
        p_top_k_by_opening,
        config=config,
        rng=rng,
        gate_on_boundary=len(opening_ids) > config.top_k,
    )
    return result[1] if result is not None else None
