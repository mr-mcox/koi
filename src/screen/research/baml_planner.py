"""Live BAML adapter for the DecidePlan function.

Coerces the generated `baml_client.types.StopAction` into the canonical
`screen.research.actions.StopAction`. Field names match field-for-field;
`test_loop_baml_shape.py` pins this at test time.

Also owns the deterministic composite-uncertainty ranking that picks the
planner's `primary_target` for each turn. The ranking is pure: it reads the
current assertions and operator rulings, never a stored history.
"""

import math
from typing import assert_never

from screen.baml_client.sync_client import b
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.context import FetchContext, SearchContext
from screen.research.state import LoopState
from screen.score.types import ScoringConfig
from screen.types import Assertion, DimensionRuling, Provenance


def _prior_queries_text(state: LoopState) -> str:
    """Render prior search queries as a short semicolon-joined string.

    Grounds the prompt's "avoid repeating a prior query" instruction in an
    actual value instead of leaving it a dangling template reference.
    """
    if not state.prior_queries:
        return "(none)"
    return "; ".join(state.prior_queries)


def last_context_text(state: LoopState) -> str:
    """Render state.last_context to a short prose paragraph for the planner.

    Returns an empty string when last_context is None (first cycle).
    """
    ctx = state.last_context
    if ctx is None:
        return ""
    if isinstance(ctx, FetchContext):
        targets = ", ".join(ctx.targets_added) if ctx.targets_added else "(none)"
        snippet_line = f" Snippet: {ctx.snippet!r}" if ctx.snippet else ""
        return (
            f"Last action: fetched {ctx.url}. "
            f"Assertions added for targets: {targets}.{snippet_line}"
        )
    if isinstance(ctx, SearchContext):
        if not ctx.hits:
            return f"Last action: searched {ctx.query!r}. Got 0 hits."
        lines = [f"Last action: searched {ctx.query!r}. Results:"]
        for i, hit in enumerate(ctx.hits, start=1):
            title = hit.get("title") or hit.get("url", "")
            url = hit.get("url", "")
            snippet = hit.get("snippet") or hit.get("raw_content", "")[:300]
            lines.append(f"{i}. {title} — {url}\n   {snippet}")
        return "\n".join(lines)
    assert_never(ctx)  # pragma: no cover


def _assertion_weight_by_target(
    assertions: list[Assertion], provenance_weight: dict[Provenance, float]
) -> dict[str, float]:
    """Provenance-weighted effective count per target."""
    counts: dict[str, float] = {}
    for a in assertions:
        counts[a.target] = counts.get(a.target, 0.0) + provenance_weight.get(a.provenance, 0.0)
    return counts


def _target_uncertainty(
    target: str,
    *,
    n_by_target: dict[str, float],
    rulings: dict[str, DimensionRuling],
    hw_max: float,
    hw_min: float,
) -> float:
    """Composite uncertainty for one target.

    If the operator has pinned a `DimensionRuling` for this target, the
    operator's stated settledness drives the signal: low settledness means
    high uncertainty (dig here), high settledness means low uncertainty
    (leave it). For targets without a ruling, fall back to assertion-derived
    half-width from the provenance-weighted count.

    The two signals are never averaged; the operator pin overrides the
    assertion count when present, matching the wall that models do not
    manufacture or update rulings (F16).
    """
    ruling = rulings.get(target)
    if ruling is not None:
        settledness = getattr(ruling, "settledness", 0.0)
        return hw_max - settledness * (hw_max - hw_min)
    n = n_by_target.get(target, 0.0)
    return 1.0 / math.sqrt(n + 1.0)


def rank_targets(state: LoopState, config: ScoringConfig) -> list[tuple[str, float]]:
    """Rank all known targets by composite uncertainty, descending.

    Ties are broken by target slug for deterministic ordering.
    """
    n_by_target = _assertion_weight_by_target(state.assertions, config.provenance_weight)
    targets = state.targets or list(dict.fromkeys(list(n_by_target) + list(state.rulings)))
    uncertainties = {
        target: _target_uncertainty(
            target,
            n_by_target=n_by_target,
            rulings=state.rulings,
            hw_max=config.dimension_ruling_hw_max,
            hw_min=config.dimension_ruling_hw_min,
        )
        for target in targets
    }
    return sorted(uncertainties.items(), key=lambda item: (-item[1], item[0]))


def select_primary_target(state: LoopState, config: ScoringConfig) -> str:
    """Pick the target the planner should focus on this turn.

    Sticky target: while `active_target` is set and the per-target action cap
    has not been reached, stay on that target. This prevents mid-chain thrash
    when a fetch on one target incidentally yields assertions about another.
    Once the cap is reached, re-rank and start a new sticky session.
    """
    if (
        state.active_target is not None
        and state.active_target_actions < state.active_target_action_cap
    ):
        return state.active_target
    ranked = rank_targets(state, config)
    return ranked[0][0] if ranked else "stretch"


class BAMLPlanner:
    """Calls DecidePlan via the generated BAML sync client.

    If `state.primary_target` is already set (the dispatcher owns the sticky
    target logic), it is passed through. Otherwise this planner computes it
    from the composite signal — useful for direct tests of the planner without
    the full dispatcher loop.
    """

    def __init__(self, config: ScoringConfig | None = None) -> None:
        self._config = config

    def plan(self, state: LoopState) -> list[Action]:
        primary_target = state.primary_target
        if primary_target is None and self._config is not None:
            primary_target = select_primary_target(state, self._config)
        if primary_target is None:
            primary_target = "stretch"
        generated = b.DecidePlan(
            company_name=state.company_name,
            opening_title=state.opening_title,
            rubric_text=state.rubric_text,
            primary_target=primary_target,
            last_context_text=last_context_text(state),
            prior_queries=_prior_queries_text(state),
        )
        return [_coerce(g) for g in generated]


def _coerce(generated: object) -> Action:
    """Translate a generated BAML action to the canonical domain type.

    Raises RuntimeError on an unrecognized tag — same discipline as the
    dispatcher so the error surfaces before dispatch, not inside it.
    """
    tag = getattr(generated, "tag", None)
    reason = getattr(generated, "reason", "")
    url = getattr(generated, "url", "")

    if tag == "stop":
        return StopAction(reason=str(reason))

    if tag == "fetch":
        return FetchAction(url=str(url))

    if tag == "search":
        query = getattr(generated, "query", "")
        return SearchAction(query=str(query))

    raise RuntimeError(
        f"BAMLPlanner received unrecognized action tag '{tag}' from DecidePlan. "
        "Update research.baml and add a coercion branch here."
    )
