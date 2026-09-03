"""Live BAML adapter for the DecidePlan function.

Coerces the generated `baml_client.types.StopAction` into the canonical
`screen.research.actions.StopAction`. Field names match field-for-field;
`test_loop_baml_shape.py` pins this at test time.
"""

from screen.baml_client.sync_client import b
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.context import FetchContext, SearchContext
from screen.research.state import LoopState
from screen.types import Assertion


def _targets_covered(state: LoopState) -> str:
    """Comma-separated list of unique targets already asserted.

    `domain` (domain coolness) is manual-only per domain-model.md's wall on
    Company — an automated pass never researches it. It is always reported
    as covered so DecidePlan never treats it as a gap worth a search.
    """
    seen = dict.fromkeys(a.target for a in state.assertions)
    seen.setdefault("domain", None)
    return ", ".join(seen)


def coverage_summary(assertions: list[Assertion]) -> str:
    """One-line summary of how many assertions per target have been collected.

    Format: "stretch(2), peer(1)" — only non-zero targets appear so the
    string is short enough to be useful in a prompt.
    """
    counts: dict[str, int] = {}
    for a in assertions:
        counts[a.target] = counts.get(a.target, 0) + 1
    if not counts:
        return "(none)"
    return ", ".join(f"{t}({n})" for t, n in counts.items())


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
        n = len(ctx.hits)
        return f"Last action: searched {ctx.query!r}. Got {n} hit(s)."
    return ""  # pragma: no cover — exhaustive over the two context types


class BAMLPlanner:
    """Calls DecidePlan via the generated BAML sync client."""

    def plan(self, state: LoopState) -> list[Action]:
        generated = b.DecidePlan(
            opening_id=state.opening_id,
            company_name=state.company_name,
            opening_title=state.opening_title,
            rubric_text=state.rubric_text,
            targets_covered=_targets_covered(state),
            turns_used=state.turns_used,
            turn_budget=state.turn_budget,
            last_context_text=last_context_text(state),
            coverage_summary=coverage_summary(state.assertions),
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
