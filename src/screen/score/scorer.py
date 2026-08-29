"""Pure Scorer: `(assertions, config) -> ScoreResult`. No I/O — `screen.score.loader` reads
files; this module only takes already-loaded data structures (see domain-model.md's Scorer
section: "the Scorer" is defined as this pure function, distinct from config loading).

Implements S1/S2/S3/S8 (docs/architecture/decisions.md): an unexamined target is a wide
Uniform(-1, +1); a target with counted evidence shrinks toward its sample mean; provenance
sets the effective weight of each piece of evidence, in place of the prototype's binary
Medium/High confidence gate. Constraints use the same shrinkage math, affine-mapped from
[-1, 1] onto their configured tolerability range instead of feeding the weighted quality sum.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import numpy as np

from screen.score.types import FIT_VALUES, ScoreResult, ScoringConfig
from screen.types import Assertion, Citation, Fit, Target

# Fixed, not `datetime.now()`: `resolve_favourably`'s hypothetical assertions must not read
# the wall clock — the Scorer is stateless and deterministic given a seed (domain-model.md
# Scorer section); a wall-clock read would break that for this one derived input.
_HYPOTHETICAL_TIME = datetime(2026, 1, 1, tzinfo=UTC)

_HYPOTHETICAL_CITATION = Citation(
    url="hypothetical://reach-counterfactual",
    quote="(hypothetical: the reach counterfactual assumes one favourable research pass)",
    host="hypothetical",
    source_provenance="hypothetical",
    independent=False,
    source_date=None,
)


@dataclass(frozen=True)
class _TargetStats:
    """Shrunk mean/half-width for one target (dimension or constraint), computed from its
    assertions' provenance-weighted fit values. `n = 0` (no counted weight) is the unexamined
    case — `mean = 0`, `half_width = 1`, i.e. Uniform(-1, +1), from the formula itself rather
    than a special-cased branch."""

    n: float
    mean: float
    half_width: float

    @property
    def is_unexamined(self) -> bool:
        return self.n == 0.0


def _target_stats(
    assertions: list[Assertion],
    config: ScoringConfig,
    target: str,
    rulings: dict[str, Fit] | None = None,
) -> _TargetStats:
    weighted_sum = 0.0
    n = 0.0
    for a in assertions:
        if a.target != target:
            continue
        weight = config.provenance_weight[a.provenance]
        fit = rulings[a.id] if rulings is not None and a.id in rulings else a.fit
        weighted_sum += weight * FIT_VALUES[fit]
        n += weight
    m = weighted_sum / n if n > 0 else 0.0
    return _TargetStats(n=n, mean=n * m / (n + 1), half_width=1.0 / math.sqrt(n + 1))


def _map_to_range(x: float, worst: float, best: float) -> float:
    """Affine-map x in [-1, 1] onto [worst, best]. x=-1 -> worst, x=+1 -> best."""
    return worst + (x + 1.0) / 2.0 * (best - worst)


def _sample_dimension(rng: np.random.Generator, stats: _TargetStats, size: int) -> np.ndarray:
    return rng.uniform(stats.mean - stats.half_width, stats.mean + stats.half_width, size)


def _sample_constraint(
    rng: np.random.Generator, stats: _TargetStats, worst: float, best: float, size: int
) -> np.ndarray:
    if stats.is_unexamined:
        return rng.uniform(worst, best, size)
    lo = _map_to_range(stats.mean - stats.half_width, worst, best)
    hi = _map_to_range(stats.mean + stats.half_width, worst, best)
    return rng.uniform(min(lo, hi), max(lo, hi), size)


def score(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit] | None = None,
) -> ScoreResult:
    """Score one assertion set. Deterministic given `config.seed` — reordering `assertions`
    never changes the result: every target's stats are a
    sum over its own assertions, order-independent by construction.

    `rulings` is an optional assertion-id -> operator-ruled `Fit` mapping (bearing
    assertion-ruling-submit): where present, the ruled fit substitutes for the assertion's
    own `fit` when computing that target's stats. Provenance-weighting is untouched — a
    ruling doesn't change how much an assertion counts, only what it says."""
    rng = np.random.default_rng(config.seed)
    size = config.samples

    dim_stats = {
        slug: _target_stats(assertions, config, slug, rulings) for slug in config.dimension_weights
    }
    weighted = np.zeros(size)
    for slug, weight in config.dimension_weights.items():
        weighted += weight * _sample_dimension(rng, dim_stats[slug], size)
    quality = np.clip((weighted / config.total_weight + 1.0) / 2.0, 0.0, 1.0)

    con_stats = {
        slug: _target_stats(assertions, config, slug, rulings) for slug in config.constraints
    }
    overall = quality.copy()
    for slug, con in config.constraints.items():
        overall *= _sample_constraint(rng, con_stats[slug], con.worst, con.best, size)

    best_weighted = sum(
        weight * (dim_stats[slug].mean + dim_stats[slug].half_width)
        for slug, weight in config.dimension_weights.items()
    )
    ceiling = min((best_weighted / config.total_weight + 1.0) / 2.0, 1.0)
    for slug, con in config.constraints.items():
        stats = con_stats[slug]
        factor = (
            con.unexamined_hi
            if stats.is_unexamined
            else _map_to_range(min(stats.mean + stats.half_width, 1.0), con.worst, con.best)
        )
        ceiling *= max(0.0, min(factor, 1.0))

    return ScoreResult(trace=overall, bar=config.bar, ceiling=ceiling)


def unexamined_targets(assertions: list[Assertion], config: ScoringConfig) -> list[str]:
    """Every scoring dimension or constraint with zero effective evidence weight — the
    targets a counterfactual reach pass would resolve."""
    counted: dict[str, float] = defaultdict(float)
    for a in assertions:
        counted[a.target] += config.provenance_weight[a.provenance]
    all_targets = list(config.dimension_weights) + list(config.constraints)
    return [slug for slug in all_targets if counted.get(slug, 0.0) == 0.0]


def resolve_favourably(assertions: list[Assertion], config: ScoringConfig) -> list[Assertion]:
    """The counterfactual reach scores against: every unexamined target gets one hypothetical
    good research pass — a `Strong`, `model_proposed` assertion (the "reach" side of the
    standing/reach pair, domain-model.md Scorer section). Not the
    theoretical maximum: `ScoreResult.ceiling` is already that, and it can't distinguish an
    empty record from a well-researched one (S5 · The queue reads a standing/reach pair;
    reach never sorts, docs/architecture/decisions.md)."""
    targets = unexamined_targets(assertions, config)
    hypothetical = [
        Assertion(
            id=f"hypothetical-{slug}",
            target=cast(Target, slug),
            fit="Strong",
            provenance="model_proposed",
            chunk="(hypothetical: one favourable research pass, reach counterfactual)",
            citations=[_HYPOTHETICAL_CITATION],
            created_at=_HYPOTHETICAL_TIME,
        )
        for slug in targets
    ]
    return [*assertions, *hypothetical]
