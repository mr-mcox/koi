"""Aggregate remaining-uncertainty per opening: the draw-weight signal for
`research-batch`'s per-turn opening choice (research-pass-bandit bearing).

Pure `(assertions, rulings, dimension_rulings, config) -> float` — no I/O, mirroring
`triage.py`/`scorer.py`.
"""

from __future__ import annotations

import numpy as np

from screen.score.scorer import stats_for_target
from screen.score.types import ScoringConfig
from screen.types import Assertion, DimensionRuling, Fit


def aggregate_uncertainty(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit] | None = None,
    dimension_rulings: dict[str, DimensionRuling] | None = None,
) -> float:
    """Dimension-weighted sum of `TargetStats.half_width` across every dimension and
    constraint. Constraints are weighted at `max(config.dimension_weights.values())` — a
    one-line policy constant rather than a new `scoring.yaml` dial, acknowledging their
    measured dominance without adding an unmeasured knob (bearing Approach)."""
    max_dimension_weight = max(config.dimension_weights.values())
    total = 0.0
    for slug, weight in config.dimension_weights.items():
        stats = stats_for_target(assertions, config, slug, rulings, dimension_rulings)
        total += weight * stats.half_width
    for slug in config.constraints:
        stats = stats_for_target(assertions, config, slug, rulings, dimension_rulings)
        total += max_dimension_weight * stats.half_width
    return total


def draw_opening[K](weights: dict[K, float], rng: np.random.Generator) -> K:
    """Draw one key from `weights`, probability proportional to its value — the
    weighted-not-argmax sampling the operator asked for (bearing Agreed). `rng` is
    threaded across successive calls by the caller, not reseeded per draw, so a batch's
    whole sequence is reproducible from one `config.seed` (bearing Approach)."""
    keys = list(weights)
    values = np.array([weights[k] for k in keys], dtype=float)
    probabilities = values / values.sum()
    index = rng.choice(len(keys), p=probabilities)
    return keys[index]
