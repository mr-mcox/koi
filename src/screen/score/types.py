"""Pure data shapes for the Scorer (docs/architecture/domain-model.md, Scorer section).
`ScoreResult` stores the Monte Carlo trace plus `bar` and the closed-form
`ceiling` — nothing else is frozen that could drift out of agreement with the
trace it was computed from. `standing`, `hits`, `p_stderr`, and `unreachable`
are properties computed from those three fields on read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from screen.types import Fit, Provenance

FIT_VALUES: dict[Fit, float] = {"Poor": -1.0, "Mixed": 0.0, "Strong": 1.0}


@dataclass(frozen=True)
class ConstraintRange:
    """A constraint's tolerability support, derived from `rubric.yaml`'s situation labels.

    `worst`/`best` are the narrowest and widest examined-situation bounds (excluding "not
    examined"); an assertion's shrunk fit value is affine-mapped onto `[worst, best]`.
    `unexamined_lo/hi` is the rubric's own declared "not examined" range, used directly
    when a constraint has no counted evidence — not derived from `worst`/`best`, because the
    rubric states this prior explicitly rather than leaving it implied by the examined
    situations (rubric.yaml's `location.situations` "Not examined" note).
    """

    worst: float
    best: float
    unexamined_lo: float
    unexamined_hi: float


@dataclass(frozen=True)
class Bands:
    """Queue band thresholds (S5 · The queue reads a standing/reach pair; reach never sorts,
    docs/architecture/decisions.md). Ported from the prototype's `config.toml` — see
    `scoring.yaml` and open-questions.md OQ9."""

    reach_wide: float
    reach_capped: float
    contender: float
    settled: float


@dataclass(frozen=True)
class ScoringConfig:
    """Everything the Scorer needs, pre-loaded. No I/O happens past this point —
    `screen.score.loader` is where `rubric.yaml`/`scoring.yaml` get read."""

    bar: float
    seed: int
    samples: int
    provenance_weight: dict[Provenance, float]
    bands: Bands
    dimension_weights: dict[str, int]
    constraints: dict[str, ConstraintRange]
    dimension_ruling_hw_max: float
    dimension_ruling_hw_min: float

    @property
    def total_weight(self) -> int:
        return sum(self.dimension_weights.values())


@dataclass(frozen=True)
class ScoreResult:
    """One Monte Carlo run of `overall` over `samples` draws. `standing` and `reach`
    (docs/architecture/domain-model.md, Scorer section) are two instances of this same type,
    scored against two different assertion sets — not fields bolted onto one record."""

    trace: np.ndarray = field(compare=False, repr=False)
    bar: float
    ceiling: float

    @property
    def samples(self) -> int:
        return len(self.trace)

    @property
    def hits(self) -> int:
        return int(np.count_nonzero(self.trace > self.bar))

    @property
    def standing(self) -> float:
        return self.hits / self.samples

    @property
    def p_stderr(self) -> float:
        """Monte Carlo standard error on `standing`. In the doldrums, `standing` is estimated
        from a handful of hits — two results can differ by less than this and the ordering,
        while reproducible, is not a real one (S6's corollary)."""
        p = self.standing
        return (p * (1 - p) / self.samples) ** 0.5

    @property
    def unreachable(self) -> bool:
        """No draw of this distribution can clear the bar (S4 · Unreachability is analytic,
        not sampled, docs/architecture/decisions.md) — the analytic ceiling, not a sampled
        zero, decides this."""
        return self.ceiling <= self.bar
