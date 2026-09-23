"""Hand-written dispatch loop — Shape 1 invariant.

DecidePlan returns a plan; the dispatcher owns every side effect.
Any action tag without a dedicated dispatch branch raises RuntimeError
rather than falling through, so adding new actions is always explicit.

The loop is synchronous. State is immutable; each action handler returns
an updated LoopState, which is threaded into the next call.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from screen.browser import BrowserError, BrowserProtocol
from screen.extract.extract import extract_assertions
from screen.extract.protocol import ExtractorProtocol
from screen.intake.events import ResearchTraceEvent
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.baml_planner import select_primary_target
from screen.research.context import FetchContext, SearchContext
from screen.research.protocol import PlannerProtocol
from screen.research.state import LoopState, PassSummary
from screen.score.types import ScoringConfig
from screen.types import Assertion


@dataclass(frozen=True)
class DispatchDeps:
    """The dispatch loop's effect ports, bundled so adding a new hook (as
    `on_assertions` did) touches this one type instead of every handler's
    signature and every call site that relays it."""

    browser: BrowserProtocol
    extractor: ExtractorProtocol
    on_event: Callable[..., None]
    on_assertions: Callable[[list[Assertion]], None] | None = None


def _targets_covered(state: LoopState) -> list[str]:
    """Unique targets with at least one assertion, in first-seen order."""
    return list(dict.fromkeys(a.target for a in state.assertions))


def _target_assertion_counts(state: LoopState) -> dict[str, int]:
    """Assertion count per target, so a resume can detect a run that repeated a
    target already holding assertions but added none *new* — `targets_covered`
    alone is a membership set and can't distinguish that from real growth."""
    counts: dict[str, int] = {}
    for a in state.assertions:
        counts[a.target] = counts.get(a.target, 0) + 1
    return counts


def _plan_request(state: LoopState) -> dict[str, object]:
    """Snapshot of what the planner had to decide from, for the audit trail.

    Omits `page_content` and `rubric_text` — static per pass, and large;
    everything here is what actually varies turn to turn.
    """
    return {
        "opening_id": state.opening_id,
        "company_id": state.company_id,
        "company_name": state.company_name,
        "opening_title": state.opening_title,
        "turns_used": state.turns_used,
        "turn_budget": state.turn_budget,
        "primary_target": state.primary_target,
        "active_target": state.active_target,
        "active_target_actions": state.active_target_actions,
        "prior_queries": list(state.prior_queries),
        "visited_urls": list(state.visited_urls),
        "targets_covered": _targets_covered(state),
        "target_assertion_counts": _target_assertion_counts(state),
        "last_context": (
            state.last_context.model_dump(mode="json") if state.last_context is not None else None
        ),
    }


def _advance_active_target(state: LoopState) -> LoopState:
    """Increment the sticky-target counter after a budget-consuming action.

    If the action was planned for a new primary target, start a new sticky
    session at 1. If it was planned for the current active target, increment.
    If `primary_target` is not set (e.g. tests with a FakePlanner), leave the
    state unchanged.
    """
    if state.primary_target is None:
        return state
    if state.primary_target == state.active_target:
        return state.model_copy(update={"active_target_actions": state.active_target_actions + 1})
    return state.model_copy(
        update={
            "active_target": state.primary_target,
            "active_target_actions": 1,
        }
    )


def dispatch(
    state: LoopState,
    *,
    planner: PlannerProtocol,
    deps: DispatchDeps,
    scoring_config: ScoringConfig | None = None,
) -> PassSummary:
    """Run one research pass and return a summary.
    Loops until StopAction or search budget exhaustion.
    Raises RuntimeError on empty action lists or unrecognized tags.

    `scoring_config` is required for the composite uncertainty ranking that
    selects the planner's `primary_target` each turn. When omitted, the loop
    trusts whatever `primary_target` is already on `state` (used by tests).
    """
    current = state
    while True:
        if scoring_config is not None:
            primary_target = select_primary_target(current, scoring_config)
            current = current.model_copy(update={"primary_target": primary_target})

        request = _plan_request(current)
        actions = planner.plan(current)
        deps.on_event(
            ResearchTraceEvent(
                ts=datetime.now(UTC),
                tool="decide_plan",
                request=request,
                response={"actions": [a.model_dump(mode="json") for a in actions]},
            )
        )
        if not actions:
            raise RuntimeError(
                "Planner returned an empty action list — must include at least [stop]."
            )
        action = actions[0]
        result = _dispatch_one(action, current, deps)
        if isinstance(result, PassSummary):
            return result
        current = _advance_active_target(result)

        # Budget guard fires after state is updated, before the next plan() call.
        if current.turns_used >= current.turn_budget:
            return PassSummary(
                opening_id=current.opening_id,
                company_id=current.company_id,
                assertions_written=len(current.assertions),
                turns_used=current.turns_used,
                stopped_reason="turn budget exhausted",
            )


def _dispatch_one(
    action: Action,
    state: LoopState,
    deps: DispatchDeps,
) -> PassSummary | LoopState:
    if action.tag == "stop":
        assert isinstance(action, StopAction)
        return PassSummary(
            opening_id=state.opening_id,
            company_id=state.company_id,
            assertions_written=len(state.assertions),
            turns_used=state.turns_used,
            stopped_reason=action.reason,
        )

    if action.tag == "search":
        assert isinstance(action, SearchAction)
        return _handle_search(action, state, deps)

    if action.tag == "fetch":
        assert isinstance(action, FetchAction)
        return _handle_fetch(action, state, deps)

    raise RuntimeError(
        f"Unrecognized action tag '{action.tag}'. "
        "Extend the dispatcher when adding new action types."
    )


def _handle_search(
    action: SearchAction,
    state: LoopState,
    deps: DispatchDeps,
) -> LoopState:
    """Issue a search query, record the event, and return updated state.
    Zero hits is valid; last_context records the empty result and the
    planner decides whether to refine the query. A BrowserError (e.g. Tavily
    transport failure) is recorded the same way — as a turn with zero hits —
    so a single failed search doesn't abort the pass when the planner can
    try something else.
    """
    try:
        hits = deps.browser.search(action.query)
    except BrowserError as exc:
        deps.on_event(
            ResearchTraceEvent(
                ts=datetime.now(UTC),
                tool="tavily_search",
                request={"query": action.query},
                response={"error": str(exc), "details": exc.details},
            )
        )
        return state.model_copy(
            update={
                "turns_used": state.turns_used + 1,
                "prior_queries": list(state.prior_queries) + [action.query],
                "last_context": SearchContext(query=action.query, hits=[]),
            }
        )
    deps.on_event(
        ResearchTraceEvent(
            ts=datetime.now(UTC),
            tool="tavily_search",
            request={"query": action.query},
            response={"results": list(hits)},
        )
    )
    return state.model_copy(
        update={
            "turns_used": state.turns_used + 1,
            "prior_queries": list(state.prior_queries) + [action.query],
            "last_context": SearchContext(query=action.query, hits=list(hits)),
        }
    )


def _handle_fetch(
    action: FetchAction,
    state: LoopState,
    deps: DispatchDeps,
) -> LoopState:
    """Fetch a URL, extract assertions, return updated state for the next cycle.

    Duplicate URLs are silently skipped — FetchContext records the URL with
    empty targets_added so the planner can see it was attempted.
    Zero new assertions is not an error and does not force stop.

    `deps.on_assertions`, when set, is called with the new assertions (never
    empty) so the caller can persist them — `dispatch` does no I/O itself.
    """
    if action.url in state.visited_urls:
        return state.model_copy(
            update={
                "last_context": FetchContext(
                    url=action.url,
                    targets_added=[],
                    snippet="",
                )
            }
        )

    try:
        hit = deps.browser.fetch(action.url)
    except BrowserError as exc:
        deps.on_event(
            ResearchTraceEvent(
                ts=datetime.now(UTC),
                tool="tavily_extract",
                request={"urls": [action.url]},
                response={"error": str(exc), "details": exc.details, "results": []},
            )
        )
        return state.model_copy(
            update={
                "visited_urls": list(state.visited_urls) + [action.url],
                "turns_used": state.turns_used + 1,
                "last_context": FetchContext(
                    url=action.url,
                    targets_added=[],
                    snippet="",
                ),
            }
        )
    raw_content: str = hit.get("raw_content") or ""
    deps.on_event(
        ResearchTraceEvent(
            ts=datetime.now(UTC),
            tool="tavily_extract",
            request={"urls": [action.url]},
            response={"results": [{"url": action.url, "raw_content": raw_content}]},
        )
    )

    new_assertions = extract_assertions(
        raw_content,
        state.rubric_text,
        list(state.assertions),
        extractor=deps.extractor,
    )

    if new_assertions and deps.on_assertions is not None:
        deps.on_assertions(new_assertions)

    targets_added = [a.target for a in new_assertions]
    snippet = raw_content[:500]

    return state.model_copy(
        update={
            "assertions": list(state.assertions) + new_assertions,
            "visited_urls": list(state.visited_urls) + [action.url],
            "turns_used": state.turns_used + 1,
            "last_context": FetchContext(
                url=action.url,
                targets_added=targets_added,
                snippet=snippet,
            ),
        }
    )
