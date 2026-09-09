"""Glue between the FastAPI routes and the pure Scorer (`screen.score`).
Routes call `score_opening`, not `score()`/`resolve_favourably()` directly — the
standing/reach recipe (S5, docs/architecture/decisions.md) lives in exactly one place,
and this module has no I/O of its own, so it's testable against synthetic assertions
without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from screen.score.interval import credible_interval
from screen.score.scorer import resolve_favourably, score
from screen.score.types import ScoreResult, ScoringConfig
from screen.types import Assertion, AssertionRuling, DimensionRuling, Fit


@dataclass(frozen=True)
class OpeningScore:
    standing: float
    reach: float
    ceiling: float
    unreachable: bool
    # Display glyph statistics for the `overall` trace: `median` is the glyph's dot,
    # `low`/`high` its q10/q90 bar. Distinct from `standing` (`P(overall > bar)`, a
    # single scalar with no per-draw quantile of its own) — the two live on different
    # axes and neither is derived from the other.
    low: float
    median: float
    high: float
    # The full standing ScoreResult, not just its scalar: callers computing
    # crossing-probability need the raw trace to compare against another opening's.
    standing_result: ScoreResult = field(compare=False, repr=False)


def score_opening(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit] | None = None,
    dimension_rulings: dict[str, DimensionRuling] | None = None,
) -> OpeningScore:
    """Standing scores `assertions` as they exist; reach scores the counterfactual
    where every unexamined target has one hypothetical good research pass. The pair is
    returned together so a caller can't accidentally sort by reach (S5).
    `rulings` (assertion id -> operator-ruled `Fit`) passes straight through to both
    calls — an override changes what the ruled assertion says everywhere it's used,
    including inside the reach counterfactual's real (non-hypothetical) assertions.
    pinned target is superseded in both standing and reach (bearing dimension-ruling)."""
    standing = score(assertions, config, rulings, dimension_rulings)
    reach = score(resolve_favourably(assertions, config), config, rulings, dimension_rulings)
    low, median, high = credible_interval(standing)
    return OpeningScore(
        standing=standing.standing,
        reach=reach.standing,
        ceiling=standing.ceiling,
        unreachable=standing.unreachable,
        low=low,
        median=median,
        high=high,
        standing_result=standing,
    )


def latest_ruling_by_assertion(
    rulings: list[AssertionRuling],
) -> dict[str, AssertionRuling]:
    """Rulings are append-only — re-rating is expected and noisy in both directions,
    not an error — so keep the most recent one per assertion for scoring. Callers are
    expected to pass rulings ordered by `created_at` ascending; the last write per
    assertion id wins."""
    return {ruling.assertion_id: ruling for ruling in rulings}


def dimension_rulings_by_target(
    rulings: list[DimensionRuling],
) -> dict[str, DimensionRuling]:
    """One row per `(opening_id, target)` by construction (upsert, migration 0005's
    unique constraint) — no dedupe needed, just a lookup keyed by target."""
    return {ruling.target: ruling for ruling in rulings}
