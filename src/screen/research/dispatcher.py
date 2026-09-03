"""Hand-written dispatch loop — Shape 1 invariant.

DecidePlan returns a plan; the dispatcher owns every side effect.
Any action tag without a dedicated dispatch branch raises RuntimeError
rather than falling through, so adding new actions is always explicit.

The loop is synchronous. State is immutable; each action handler returns
an updated LoopState, which is threaded into the next call.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from screen.browser import BrowserProtocol
from screen.extract.extract import extract_assertions
from screen.extract.protocol import ExtractorProtocol
from screen.intake.events import ResearchTraceEvent
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.context import FetchContext, SearchContext
from screen.research.protocol import PlannerProtocol
from screen.research.state import LoopState, PassSummary


def _targets_covered(state: LoopState) -> list[str]:
    """Unique targets with at least one assertion, in first-seen order."""
    return list(dict.fromkeys(a.target for a in state.assertions))


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
        "prior_queries": list(state.prior_queries),
        "visited_urls": list(state.visited_urls),
        "targets_covered": _targets_covered(state),
        "last_context": (
            state.last_context.model_dump(mode="json") if state.last_context is not None else None
        ),
    }


def dispatch(
    state: LoopState,
    *,
    planner: PlannerProtocol,
    browser: BrowserProtocol,
    extractor: ExtractorProtocol,
    on_event: Callable[..., None],
) -> PassSummary:
    """Run one research pass and return a summary.
    Loops until StopAction or search budget exhaustion.
    Raises RuntimeError on empty action lists or unrecognized tags.
    """
    current = state
    while True:
        request = _plan_request(current)
        actions = planner.plan(current)
        on_event(
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
        result = _dispatch_one(action, current, browser, extractor, on_event)
        if isinstance(result, PassSummary):
            return result
        current = result
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
    browser: BrowserProtocol,
    extractor: ExtractorProtocol,
    on_event: Callable[..., None],
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
        return _handle_search(action, state, browser, on_event)

    if action.tag == "fetch":
        assert isinstance(action, FetchAction)
        return _handle_fetch(action, state, browser, extractor, on_event)

    raise RuntimeError(
        f"Unrecognized action tag '{action.tag}'. "
        "Extend the dispatcher when adding new action types."
    )


def _handle_search(
    action: SearchAction,
    state: LoopState,
    browser: BrowserProtocol,
    on_event: Callable[..., None],
) -> LoopState:
    """Issue a search query, record the event, and return updated state.

    Zero hits is valid; last_context records the empty result and the
    planner decides whether to refine the query.
    """
    hits = browser.search(action.query)

    on_event(
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
    browser: BrowserProtocol,
    extractor: ExtractorProtocol,
    on_event: Callable[..., None],
) -> LoopState:
    """Fetch a URL, extract assertions, return updated state for the next cycle.

    Duplicate URLs are silently skipped — FetchContext records the URL with
    empty targets_added so the planner can see it was attempted.
    Zero new assertions is not an error and does not force stop.
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

    hit = browser.fetch(action.url)
    raw_content: str = hit.get("raw_content") or ""

    on_event(
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
        extractor=extractor,
    )

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
