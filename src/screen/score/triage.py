"""Rating-VOI triage: rank unrated assertion/dimension tasks on one opening by how much
rating them could move `standing` (review-ux/rating-voi-triage bearing).

Pure `(assertions, config) -> [RatingTaskCandidate]` — no I/O, mirroring `scorer.py`.
Never writes back to `Assertion`/`DimensionRuling`; the swing number is a route/display
computation only (bearing Approach — reopening confidence-as-multiplier is the failure
mode this stays clear of, decisions.md S8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from screen.score.scorer import score
from screen.score.types import ScoringConfig
from screen.types import Assertion, DimensionRuling, Fit, Target

# Fixed, not `datetime.now()`: this placeholder's `created_at` never reaches scoring math
# (only `mean`/`settledness` do, via `_dimension_ruling_stats`) and the Scorer stays
# deterministic given a seed regardless (domain-model.md Scorer section).
_PLACEHOLDER_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RatingTaskCandidate:
    """One unrated task and its estimated leverage. `assertion_id` is set for an
    assertion-ruling task, `None` for a whole-dimension task — the two task kinds stay
    distinguishable the same way `AssertionRuling`/`DimensionRuling` do (Wall-adjacent:
    sibling concepts, not a scoped union)."""

    target: Target
    assertion_id: str | None
    swing: float


def _swing(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit],
    dimension_rulings: dict[str, DimensionRuling],
    *,
    override_rulings: dict[str, Fit] | None = None,
    override_dimension_rulings: dict[Target, DimensionRuling] | None = None,
) -> float:
    """|standing(best-case override) - standing(worst-case override)| for one task,
    holding everything else fixed. Symmetric by design (checkpoint, this session): rating
    an already-`Poor` assertion `Strong` and rating it `Poor`-confirmed can each move
    standing, and the proxy doesn't presume which way the operator will rule."""
    best_rulings = dict(rulings)
    worst_rulings = dict(rulings)
    best_dim = dict(dimension_rulings)
    worst_dim = dict(dimension_rulings)

    if override_rulings is not None:
        assertion_id = next(iter(override_rulings))
        best_rulings[assertion_id] = "Strong"
        worst_rulings[assertion_id] = "Poor"
    if override_dimension_rulings is not None:
        target = next(iter(override_dimension_rulings))
        best_dim[target] = DimensionRuling(
            id=str(uuid4()),
            opening_id=override_dimension_rulings[target].opening_id,
            target=target,
            mean=1.0,
            settledness=1.0,
            created_at=override_dimension_rulings[target].created_at,
            covered_assertion_ids=[],
        )
        worst_dim[target] = DimensionRuling(
            id=str(uuid4()),
            opening_id=override_dimension_rulings[target].opening_id,
            target=target,
            mean=-1.0,
            settledness=1.0,
            created_at=override_dimension_rulings[target].created_at,
            covered_assertion_ids=[],
        )

    best = score(assertions, config, best_rulings, best_dim)
    worst = score(assertions, config, worst_rulings, worst_dim)
    return abs(best.standing - worst.standing)


def rating_task_candidates(
    assertions: list[Assertion],
    config: ScoringConfig,
    rulings: dict[str, Fit] | None = None,
    dimension_rulings: dict[str, DimensionRuling] | None = None,
) -> list[RatingTaskCandidate]:
    """Every unrated assertion and unrated-or-stale dimension target on one opening, ranked
    by estimated swing, truncated to `config.rating_task_budget`.

    An assertion covered by a pin's snapshot is excluded — the pin already accounts for it
    (scorer.py `stats_for_target`), so rating it can't move anything. An assertion filed
    after the pin's snapshot is uncovered, new evidence the pin hasn't priced in yet, and
    stays a candidate like any other unrated assertion (dimension-ruling-drift bearing:
    reopening is binary on any uncovered assertion). A dimension target with zero
    assertions is excluded too — there is nothing to review, so "rate this dimension" isn't
    an actionable task; that gap is a research question, not a rating one. A pinned target
    is itself a whole-dimension candidate again once it has any uncovered assertion (the
    pin is stale) — an unpinned target is always eligible, a pinned one only when stale.
    """
    rulings = rulings or {}
    dimension_rulings = dimension_rulings or {}

    targets_with_assertions = {a.target for a in assertions}

    def covered_ids(target: str) -> set[str]:
        pin = dimension_rulings.get(target)
        return set(pin.covered_assertion_ids) if pin is not None else set()

    candidates: list[RatingTaskCandidate] = []
    for a in assertions:
        if a.id in rulings or a.id in covered_ids(a.target):
            continue
        swing = _swing(
            assertions, config, rulings, dimension_rulings, override_rulings={a.id: a.fit}
        )
        candidates.append(RatingTaskCandidate(target=a.target, assertion_id=a.id, swing=swing))

    all_targets = list(config.dimension_weights) + list(config.constraints)
    for slug in all_targets:
        target = cast(Target, slug)
        if target not in targets_with_assertions:
            continue
        target_assertion_ids = {a.id for a in assertions if a.target == target}
        is_stale = target in dimension_rulings and not target_assertion_ids <= covered_ids(target)
        if target in dimension_rulings and not is_stale:
            continue
        placeholder = DimensionRuling(
            id=str(uuid4()),
            opening_id="placeholder",
            target=target,
            mean=0.0,
            settledness=0.0,
            created_at=_PLACEHOLDER_TIME,
            covered_assertion_ids=[],
        )
        swing = _swing(
            assertions,
            config,
            rulings,
            dimension_rulings,
            override_dimension_rulings={target: placeholder},
        )
        candidates.append(RatingTaskCandidate(target=target, assertion_id=None, swing=swing))

    candidates.sort(key=lambda c: c.swing, reverse=True)
    return candidates[: config.rating_task_budget]
