"""Display glyph statistics for one opening's `overall` trace: the median dot and its
q10/q90 credible interval. All three live on the same `overall`-quality axis (0-1) that
the K-th opening's boundary tick is also plotted on — none of them is `standing`, which
is `P(overall > bar)`, a single scalar with no per-draw quantile of its own, so the
trace's quantiles do not bracket it.

Display-layer arithmetic over an already-produced `ScoreResult`, same posture as
`screen.score.boundary` — never written back to `Assertion`/`DimensionRuling`/`Scorer`
(domain-model.md's wall: raw positions never reach the scorer).
"""

from __future__ import annotations

import numpy as np

from screen.score.types import ScoreResult

_LOW_QUANTILE = 0.10
_HIGH_QUANTILE = 0.90


def credible_interval(result: ScoreResult) -> tuple[float, float, float]:
    """`(low, median, high)` of the `overall` trace — the trace's own 10th/50th/90th
    percentile, a display convention rather than a model parameter (bearing Approach);
    promote the quantile pair to `scoring.yaml` only if real use shows the need to tune it."""
    low, median, high = np.quantile(result.trace, [_LOW_QUANTILE, 0.5, _HIGH_QUANTILE])
    return float(low), float(median), float(high)
