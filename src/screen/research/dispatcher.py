"""Hand-written dispatch loop — Shape 1 invariant.

The Navigator returns a plan; the dispatcher owns every side effect.
Any action tag without a dedicated dispatch branch raises RuntimeError
rather than falling through, so adding new actions is always explicit.

The loop is synchronous. State is immutable; each action handler returns
an updated LoopState, which is threaded into the next call.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import get_args

from screen.browser import Browser, BrowserError
from screen.extract.extract import extract_assertions
from screen.extract.protocol import Extractor
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.backlog import rank_link_backlog
from screen.research.context import FetchContext, SearchContext
from screen.research.protocol import LinkScorer, Navigator, Surveyor
from screen.research.question import render_assertion_history, render_yield_summary
from screen.research.state import LoopState, PassSummary
from screen.research_trace.events import (
    ExtractEvent,
    ExtractRequest,
    ExtractResponse,
    ExtractResult,
    NavigateEvent,
    NavigateRequest,
    NavigateResponse,
    ResearchTraceEvent,
    SearchEvent,
    SearchRequest,
    SearchResponse,
    SurveyEvent,
    SurveyRequest,
    SurveyResponse,
)
from screen.types import Assertion, Target


@dataclass(frozen=True)
class DispatchDeps:
    """The dispatch loop's effect ports, bundled so a new hook touches this one type
    instead of every handler's signature and every call site that relays it.

    `link_scorer`/`link_allowed` are the backlog-ranking seam: when both are set,
    the loop ranks the unvisited links replayed from prior passes once, before the
    first navigator turn, and hands the navigator the surviving shortlist.
    """

    browser: Browser
    extractor: Extractor
    on_event: Callable[[ResearchTraceEvent], None]
    on_assertions: Callable[[list[Assertion]], None] | None = None
    link_scorer: LinkScorer | None = None
    link_allowed: Callable[[str], bool] | None = None


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


def _plan_request(state: LoopState) -> NavigateRequest:
    """Snapshot of what the navigator had to decide from, for the audit trail.

    Omits `page_content` and `rubric_text` — static per pass, and large;
    everything here is what actually varies turn to turn.
    """
    return NavigateRequest(
        opening_id=state.opening_id,
        company_id=state.company_id,
        company_name=state.company_name,
        opening_title=state.opening_title,
        turns_used=state.turns_used,
        turn_budget=state.turn_budget,
        primary_target=state.primary_target,
        research_question=state.research_question,
        prior_queries=list(state.prior_queries),
        visited_urls=list(state.visited_urls),
        targets_covered=_targets_covered(state),
        target_assertion_counts=_target_assertion_counts(state),
        assertion_history=render_assertion_history(
            state.assertions, [state.primary_target] if state.primary_target else []
        ),
        last_context=(
            state.last_context.model_dump(mode="json") if state.last_context is not None else None
        ),
    )


def _survey(state: LoopState, surveyor: Surveyor, deps: DispatchDeps) -> LoopState:
    """Ask the Surveyor once, record the call, validate its answer against the
    rubric's live `Target` vocabulary, and fold it into state as the fixed
    `primary_target`/`research_question` for every turn in this pass.

    A dimension outside the vocabulary fails the pass loudly (RuntimeError)
    rather than being silently remapped — the Surveyor is the only target
    chooser, so there is no deterministic fallback to catch a bad answer.
    """
    question = surveyor.survey(state)
    if question.dimension not in get_args(Target):
        raise RuntimeError(
            f"Surveyor chose dimension {question.dimension!r}, which is not one of "
            f"the rubric's dimensions {list(get_args(Target))}. Fix the prompt or the "
            "rubric — this is not silently remapped."
        )
    deps.on_event(
        SurveyEvent(
            ts=datetime.now(UTC),
            request=SurveyRequest(
                company_name=state.company_name,
                opening_title=state.opening_title,
                dimensions=list(state.targets),
                yield_summary=render_yield_summary(
                    state.opening_id, state.pool_yield, state.target_stall_counts
                ),
                query_assertion_history=render_assertion_history(state.assertions, state.targets),
            ),
            response=SurveyResponse(dimension=question.dimension, question=question.question),
        )
    )
    return state.model_copy(
        update={"primary_target": question.dimension, "research_question": question.question}
    )


def dispatch(
    state: LoopState,
    *,
    navigator: Navigator,
    surveyor: Surveyor,
    deps: DispatchDeps,
) -> PassSummary:
    """Run one research pass and return a summary.
    Loops until StopAction or search budget exhaustion.
    Raises RuntimeError on empty action lists or unrecognized tags.

    `surveyor` is consulted exactly once, before the loop starts — see
    `_survey`. Every turn in the pass sees the same dimension/question.
    """
    current = _survey(state, surveyor, deps)

    if current.unvisited_links and deps.link_scorer is not None:
        ranked = rank_link_backlog(current, deps.link_scorer, deps.link_allowed)
        current = current.model_copy(update={"link_backlog": ranked})

    while True:
        request = _plan_request(current)
        actions = navigator.plan(current)
        deps.on_event(
            NavigateEvent(
                ts=datetime.now(UTC),
                request=request,
                response=NavigateResponse(actions=[a.model_dump(mode="json") for a in actions]),
            )
        )
        if not actions:
            raise RuntimeError(
                "Navigator returned an empty action list — must include at least [stop]."
            )
        action = actions[0]
        result = _dispatch_one(action, current, deps)
        if isinstance(result, PassSummary):
            return result
        current = result

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
    navigator decides whether to refine the query. A BrowserError (e.g. Tavily
    transport failure) is recorded the same way — as a turn with zero hits —
    so a single failed search doesn't abort the pass when the navigator can
    try something else.
    """
    try:
        hits = deps.browser.search(action.query)
    except BrowserError as exc:
        deps.on_event(
            SearchEvent(
                ts=datetime.now(UTC),
                request=SearchRequest(query=action.query),
                response=SearchResponse(error=str(exc), details=exc.details),
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
        SearchEvent(
            ts=datetime.now(UTC),
            request=SearchRequest(query=action.query),
            response=SearchResponse(results=list(hits)),
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
    empty targets_added so the navigator can see it was attempted.
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
            ExtractEvent(
                ts=datetime.now(UTC),
                request=ExtractRequest(urls=[action.url]),
                response=ExtractResponse(results=[], error=str(exc), details=exc.details),
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
        ExtractEvent(
            ts=datetime.now(UTC),
            request=ExtractRequest(urls=[action.url]),
            response=ExtractResponse(
                results=[ExtractResult(url=action.url, raw_content=raw_content)]
            ),
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
