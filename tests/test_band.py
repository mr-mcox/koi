"""Unit tests for `band_for` — the standing/reach pair -> queue band mapping
(S5 · The queue reads a standing/reach pair; reach never sorts, docs/architecture/decisions.md).
Constructs synthetic `ScoreResult`s directly (rather than via `score`) so each of the five
band outcomes is reached deterministically, without depending on real seed data producing
the right shape by chance.
"""

import numpy as np

from screen.score.band import band_for
from screen.score.types import Bands, ScoreResult

BANDS = Bands(reach_wide=0.50, reach_capped=0.05, contender=0.15, settled=0.02)


def _result(
    hit_fraction: float, ceiling: float, bar: float = 0.60, samples: int = 1000
) -> ScoreResult:
    hits = round(hit_fraction * samples)
    trace = np.array([bar + 0.01] * hits + [bar - 0.01] * (samples - hits))
    return ScoreResult(trace=trace, bar=bar, ceiling=ceiling)


def test_band_no_path_when_unreachable() -> None:
    standing = _result(hit_fraction=0.0, ceiling=0.40)  # ceiling below bar (0.60)
    reach = _result(hit_fraction=0.0, ceiling=0.40)
    assert band_for(standing, reach, BANDS) == "no path"


def test_band_contender_when_standing_high() -> None:
    standing = _result(hit_fraction=0.20, ceiling=0.90)
    reach = _result(hit_fraction=0.20, ceiling=0.90)
    assert band_for(standing, reach, BANDS) == "contender"


def test_band_established_when_reach_close_to_standing() -> None:
    standing = _result(hit_fraction=0.10, ceiling=0.90)
    reach = _result(hit_fraction=0.11, ceiling=0.90)  # lift < settled (0.02)
    assert band_for(standing, reach, BANDS) == "established"


def test_band_no_path_when_reach_below_capped() -> None:
    standing = _result(hit_fraction=0.0, ceiling=0.90)
    reach = _result(hit_fraction=0.02, ceiling=0.90)  # reach < reach_capped (0.05)
    assert band_for(standing, reach, BANDS) == "no path"


def test_band_capped_when_reach_between_capped_and_wide() -> None:
    standing = _result(hit_fraction=0.0, ceiling=0.90)
    reach = _result(hit_fraction=0.20, ceiling=0.90)  # between 0.05 and 0.50
    assert band_for(standing, reach, BANDS) == "capped"


def test_band_wide_open_when_reach_high() -> None:
    standing = _result(hit_fraction=0.0, ceiling=0.90)
    reach = _result(hit_fraction=0.60, ceiling=0.90)  # >= reach_wide (0.50)
    assert band_for(standing, reach, BANDS) == "wide open"
