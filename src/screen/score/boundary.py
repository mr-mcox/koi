"""Boundary-crossing probability: `P(rank crosses K)` per opening.

Compares an opening's Monte Carlo `overall` trace elementwise against the trace of
whichever opening currently holds rank K, both drawn under the shared `config.seed`.
A cheap approximation, not a resampled joint comparison: it treats the K-th opening as
a fixed reference, which misrepresents the probability only when several openings are
simultaneously contesting rank K in a way that would itself change who holds it.
Display/route-layer arithmetic over two already-produced `ScoreResult`s — never a new
Scorer primitive, and never written back to `Assertion`/`DimensionRuling`/`Scorer`
(domain-model.md's wall: raw positions never reach the scorer).
"""

from __future__ import annotations

import numpy as np

from screen.score.types import ScoreResult


def crossing_probability(opening: ScoreResult, kth: ScoreResult) -> float:
    """Fraction of samples where `opening`'s `overall` draw exceeds `kth`'s. Both
    traces must have the same sample count — guaranteed by the shared `config.seed`/
    `samples` every `score()` call uses; a mismatch here means a caller compared
    traces from different configs, not a case to tolerate."""
    if opening.trace.shape != kth.trace.shape:
        raise ValueError(
            f"trace shape mismatch: {opening.trace.shape} vs {kth.trace.shape} — "
            "traces must come from calls sharing config.seed/samples"
        )
    return float(np.mean(opening.trace > kth.trace))
