"""Glue between the FastAPI routes and the pure Scorer (`screen.score`).

Routes call `score_opening`, not `score()`/`resolve_favourably()`/`band_for()`
directly — the standing/reach/band recipe (S5, docs/architecture/decisions.md)
lives in exactly one place, and this module has no I/O of its own, so it's
testable against synthetic assertions without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

from screen.score.band import Band, band_for
from screen.score.scorer import resolve_favourably, score
from screen.score.types import ScoringConfig
from screen.types import Assertion, DimensionRuling, Fit


@dataclass(frozen=True)
class OpeningScore:
    standing: float
    reach: float
    band: Band
    ceiling: float
    unreachable: bool


def score_opening(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit] | None = None,
    dimension_rulings: dict[str, DimensionRuling] | None = None,
) -> OpeningScore:
    """Standing scores `assertions` as they exist; reach scores the counterfactual
    where every unexamined target has one hypothetical good research pass. `band`
    reads the pair (S5 · reach never sorts) — this function is where they're
    always computed together, so a caller can't accidentally sort by reach.

    `rulings` (assertion id -> operator-ruled `Fit`) passes straight through to both
    calls — an override changes what the ruled assertion says everywhere it's used,
    including inside the reach counterfactual's real (non-hypothetical) assertions.

    `dimension_rulings` (target -> `DimensionRuling`) passes through the same way — a
    pinned target is superseded in both standing and reach (bearing dimension-ruling)."""
    standing = score(assertions, config, rulings, dimension_rulings)
    reach = score(resolve_favourably(assertions, config), config, rulings, dimension_rulings)
    band = band_for(standing, reach, config.bands)
    return OpeningScore(
        standing=standing.standing,
        reach=reach.standing,
        band=band,
        ceiling=standing.ceiling,
        unreachable=standing.unreachable,
    )
