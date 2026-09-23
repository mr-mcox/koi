"""Aggregate remaining-uncertainty per opening: the draw-weight signal for
`research-batch`'s per-turn opening choice.

Pure `(assertions, rulings, config) -> float` — no I/O, mirroring `scorer.py`.
"""

from __future__ import annotations

import math

import numpy as np

from screen.score.scorer import stats_for_target
from screen.score.types import ScoringConfig
from screen.types import Assertion, Fit


def aggregate_uncertainty(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit] | None = None,
) -> float:
    """Dimension-weighted sum of `TargetStats.half_width` across every scored dimension."""
    total = 0.0
    for slug, weight in config.dimension_weights.items():
        stats = stats_for_target(assertions, config, slug, rulings)
        total += weight * stats.half_width
    return total


def boundary_weight(p_top_k: float) -> float:
    """How contested an opening's top-K membership is: `p*(1-p)`, maximized at 0.5
    (genuinely on the boundary) and zero at 0 or 1 (settled in or out)."""
    return p_top_k * (1 - p_top_k)


def target_suppression(stall_count: int) -> float:
    """Graduated down-weight for targets that have burned research turns without
    adding assertions. Logistic decay centered at 1.5 stalls, so one prior stall
    gives a slight penalty (~0.88), two a sharp one (~0.12), three-or-more makes
    the target very unlikely to be chosen again while leaving it theoretically
    reachable if every alternative is exhausted."""
    if stall_count <= 0:
        return 1.0
    return float(1.0 / (1.0 + math.exp(4.0 * (stall_count - 1.5))))


def draw_opening[K](weights: dict[K, float], rng: np.random.Generator) -> K:
    """Draw one key from `weights`, probability proportional to its value — weighted
    sampling, not argmax: an opening's remaining uncertainty should raise its odds of
    the next turn, never guarantee it, so no eligible opening's budget can be starved by
    another's persistently wider half-width. `rng` is threaded across successive calls by
    the caller, not reseeded per draw, so a whole batch's sequence is reproducible from
    one `config.seed`."""
    keys = list(weights)
    values = np.array([weights[k] for k in keys], dtype=float)
    probabilities = values / values.sum()
    index = rng.choice(len(keys), p=probabilities)
    return keys[index]
