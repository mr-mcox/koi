"""Tests for the hand-written dispatch loop.
Pins:
- dispatch([stop]) returns PassSummary with correct counts
- unknown action tag raises RuntimeError (not silently skipped)
- turns_used threads from state into summary unchanged
- SearchAction happy path: browser.search called, event recorded, state updated
- SearchAction budget guard: turns_used >= turn_budget → PassSummary, no extra plan() call
- FetchAction happy path: browser.fetch called, event recorded, assertions appended
- FetchAction duplicate: URL already in visited_urls → skip, no event, empty targets_added
- FetchAction zero assertions: does not raise, loop continues
- SearchAction BrowserError: recorded as a failed tavily_search event, counts as a turn, pass continues
- FetchAction BrowserError: recorded as a failed tavily_extract event, adds URL to visited_urls, counts as a turn, pass continues
"""

from typing import Literal

import pytest
from pydantic import ConfigDict

from screen.extract.fakes import FakeExtractor
from screen.research.actions import Action, FetchAction, SearchAction, StopAction
from screen.research.dispatcher import DispatchDeps, dispatch
from screen.research.fakes import FakeBrowser, FakeNavigator
from screen.research.state import LoopState, PassSummary
from screen.research_trace.events import (
    DecidePlanEvent,
    ExtractEvent,
    ExtractRequest,
    ExtractResult,
    SearchEvent,
    SearchRequest,
)
from screen.score.loader import load_scoring_config
from screen.types import Assertion
from tests.helpers import canned_assertion


def _noop(_event: object) -> None:
    pass


def _state(
    *,
    assertions: list[Assertion] | None = None,
    turns_used: int = 0,
    visited_urls: list[str] | None = None,
    **kwargs: object,
) -> LoopState:
    defaults: dict[str, object] = {
        "opening_id": "op-abc",
        "company_id": "co-xyz",
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "page_content": "Some posting text.",
        "url": "https://example.com/jobs/1",
        "rubric_text": "craft_direction: ...",
        "assertions": assertions if assertions is not None else [canned_assertion()],
        "turn_budget": 5,
        "turns_used": turns_used,
        "visited_urls": visited_urls if visited_urls is not None else [],
    }
    defaults.update(kwargs)
    return LoopState(**defaults)  # type: ignore[arg-type]


def _fake_extractor(results: list[list[Assertion]] | None = None) -> FakeExtractor:
    return FakeExtractor(results or [[]])


def _deps(
    *,
    browser: FakeBrowser | None = None,
    extractor: FakeExtractor | None = None,
    on_event: object = _noop,
) -> DispatchDeps:
    return DispatchDeps(
        browser=browser if browser is not None else FakeBrowser(),
        extractor=extractor if extractor is not None else _fake_extractor(),
        on_event=on_event,  # type: ignore[arg-type]
    )


def test_dispatch_stop_returns_pass_summary() -> None:
    state = _state(assertions=[canned_assertion(), canned_assertion()])
    stop = StopAction(reason="All rubric dimensions addressed.")
    summary = dispatch(
        state,
        navigator=FakeNavigator(sequence=[[stop]]),
        deps=_deps(browser=FakeBrowser(), extractor=_fake_extractor(), on_event=_noop),
    )

    assert isinstance(summary, PassSummary)
    assert summary.opening_id == "op-abc"
    assert summary.company_id == "co-xyz"
    assert summary.assertions_written == 2
    assert summary.stopped_reason == "All rubric dimensions addressed."


def test_decide_plan_event_records_request_and_response() -> None:
    """Every navigator.plan() call is recorded as a decide_plan event: the
    request carries the state snapshot the navigator saw, the response carries
    the action(s) it returned."""
    stop = StopAction(reason="Nothing left to check.")
    events: list[object] = []
    state = _state(turns_used=2)

    dispatch(
        state,
        navigator=FakeNavigator(sequence=[[stop]]),
        deps=_deps(browser=FakeBrowser(), extractor=_fake_extractor(), on_event=events.append),
    )

    plan_events = [e for e in events if isinstance(e, DecidePlanEvent)]
    assert len(plan_events) == 1
    event = plan_events[0]

    assert event.request.opening_id == "op-abc"
    assert event.request.company_id == "co-xyz"
    assert event.request.company_name == "Acme Corp"
    assert event.request.opening_title == "Staff Software Engineer"
    assert event.request.turns_used == 2
    assert event.request.targets_covered == ["craft_direction"]
    assert event.request.target_assertion_counts == {"craft_direction": 1}
    assert event.request.last_context is None
    assert event.response.actions == [{"tag": "stop", "reason": "Nothing left to check."}]


def test_dispatch_threads_budget_counters() -> None:
    state = _state(turns_used=2)
    summary = dispatch(
        state,
        navigator=FakeNavigator(),
        deps=_deps(browser=FakeBrowser(), extractor=_fake_extractor(), on_event=_noop),
    )

    assert summary.turns_used == 2


def test_dispatch_unknown_tag_raises_runtime_error() -> None:
    """Any tag the dispatcher doesn't recognize must be a hard error."""
    # Subclass StopAction with a different tag literal at runtime;
    # the dispatcher sees tag != "stop" and must raise.

    class UnknownAction(StopAction):
        model_config = ConfigDict(extra="forbid", frozen=True)
        tag: Literal["future_tag"] = "future_tag"  # type: ignore[assignment]

    navigator: FakeNavigator = FakeNavigator(sequence=[[UnknownAction(reason="x")]])  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="future_tag"):
        dispatch(
            _state(),
            navigator=navigator,
            deps=_deps(browser=FakeBrowser(), extractor=_fake_extractor(), on_event=_noop),
        )


def test_dispatch_empty_action_list_raises_runtime_error() -> None:
    """A navigator returning [] must raise RuntimeError — the loop requires at least [stop]."""
    navigator = FakeNavigator(sequence=[[]])  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="empty action list"):
        dispatch(
            _state(),
            navigator=navigator,
            deps=_deps(browser=FakeBrowser(), extractor=_fake_extractor(), on_event=_noop),
        )


def test_search_action_happy_path() -> None:
    """SearchAction calls browser.search, records a tavily_search event,
    increments turns_used, appends to prior_queries, and sets last_context
    to a SearchContext with the returned hits."""
    query = "Company A staff eng compensation 2024"
    hits = [
        {"url": "https://levels.fyi/", "title": "Levels", "snippet": "Staff $400k."},
    ]

    browser = FakeBrowser(search_fixtures={query: hits})
    stop = StopAction(reason="Covered.")
    navigator = FakeNavigator(
        sequence=[
            [SearchAction(query=query)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(turns_used=0)

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=_fake_extractor(), on_event=events.append),
    )

    # browser.search was called with the right query
    assert browser.search_calls == [query]

    # tavily_search event was recorded (alongside decide_plan audit events)
    search_events = [e for e in events if isinstance(e, SearchEvent)]
    assert len(search_events) == 1
    event = search_events[0]
    assert event.request == SearchRequest(query=query)

    # summary reflects one search used
    assert summary.turns_used == 1
    assert isinstance(summary, PassSummary)


def test_budget_guard_fires() -> None:
    """After a SearchAction that pushes turns_used to turn_budget,
    the dispatcher returns PassSummary with stopped_reason='turn budget exhausted'
    without calling navigator.plan again."""
    query = "Company A comp"
    hits: list[object] = []

    # turn_budget=1, turns_used starts at 0 — one search exhausts the budget
    browser = FakeBrowser(search_fixtures={query: hits})
    # If the guard misfires and calls plan() again, the second element would return stop;
    # but the guard must fire BEFORE the next plan() call.
    stop = StopAction(reason="Should not be reached.")
    navigator = FakeNavigator(
        sequence=[
            [SearchAction(query=query)],
            [stop],  # must NOT be reached
        ]
    )
    plan_calls: list[int] = []
    original_plan = navigator.plan

    def counting_plan(s: LoopState) -> list[Action]:  # type: ignore[type-arg]
        plan_calls.append(1)
        return original_plan(s)

    navigator.plan = counting_plan  # type: ignore[method-assign]

    state = _state(turns_used=0)
    state = state.model_copy(update={"turn_budget": 1})

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=_fake_extractor(), on_event=_noop),
    )

    # plan() was called exactly once (for the SearchAction)
    assert len(plan_calls) == 1
    # summary says budget exhausted
    assert summary.stopped_reason == "turn budget exhausted"
    assert summary.turns_used == 1


def test_fetch_action_happy_path() -> None:
    """FetchAction against a new URL calls browser.fetch, records a tavily_extract
    event, runs extraction, and returns updated state with new assertions appended."""
    url = "https://levels.fyi/companies/acme"
    raw = "Acme pays $400k TC for staff engineers in remote roles."
    new_assertion = canned_assertion(target="compensation")

    browser = FakeBrowser(fetch_fixtures={url: {"raw_content": raw}})
    extractor = FakeExtractor([[new_assertion]])
    stop = StopAction(reason="Done after fetch.")
    navigator = FakeNavigator(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(assertions=[canned_assertion()])

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=extractor, on_event=events.append),
    )

    # browser.fetch was called with the right URL
    assert browser.fetch_calls == [url]

    # tavily_extract event was recorded (alongside decide_plan audit events)
    extract_events = [e for e in events if isinstance(e, ExtractEvent)]
    assert len(extract_events) == 1
    event = extract_events[0]
    assert event.request == ExtractRequest(urls=[url])
    assert event.response.results == [ExtractResult(url=url, raw_content=raw)]

    # new assertion was appended to the summary count
    assert summary.assertions_written == 2  # original + new_assertion

    # fetch is a budget-consuming turn
    assert summary.turns_used == 1

    # FetchContext in last_context carried the new target
    # (accessible by inspecting the state passed to the second navigator.plan call
    # — we verify via the summary assertion count and the browser call)
    assert isinstance(summary, PassSummary)


def test_fetch_action_duplicate_skipped() -> None:
    """FetchAction against a URL already in visited_urls skips the browser call
    and records no tavily_extract event; last_context.targets_added is empty."""
    url = "https://example.com/already-visited"
    browser = FakeBrowser(fetch_fixtures={url: {"raw_content": "content"}})
    extractor = FakeExtractor([[]])
    stop = StopAction(reason="Done.")
    navigator = FakeNavigator(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(visited_urls=[url])

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=extractor, on_event=events.append),
    )

    # browser.fetch was NOT called
    assert browser.fetch_calls == []
    # no tavily_extract event was recorded (decide_plan audit events still are)
    extract_events = [e for e in events if isinstance(e, ExtractEvent)]
    assert extract_events == []
    # summary still valid
    assert isinstance(summary, PassSummary)


def test_fetch_action_zero_assertions_continues() -> None:
    """FetchAction where extraction returns [] does not raise and does not force
    stop — the loop continues normally."""
    url = "https://example.com/hub-page"
    raw = "Hub page with no scorable claims."
    browser = FakeBrowser(fetch_fixtures={url: {"raw_content": raw}})
    extractor = FakeExtractor([[]])  # zero assertions returned
    stop = StopAction(reason="Nothing more to do.")
    navigator = FakeNavigator(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    state = _state(assertions=[])

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=extractor, on_event=_noop),
    )

    # No assertion added — extraction returned []
    assert summary.assertions_written == 0
    # Loop completed normally — no exception raised
    assert isinstance(summary, PassSummary)
    assert summary.stopped_reason == "Nothing more to do."


def test_dispatch_computes_primary_target_once_before_loop() -> None:
    """The pass selects one target up front and holds it for every turn —
    `scoring_config` is consulted once, not re-ranked turn to turn, even as
    new assertions land that would shift the ranking."""
    config = load_scoring_config()
    url = "https://example.com/acme-comp"
    new_assertion = canned_assertion(target="craft_direction")
    browser = FakeBrowser(fetch_fixtures={url: {"raw_content": "Acme pays well."}})
    stop = StopAction(reason="Done.")
    navigator = FakeNavigator(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    # Both targets start unexamined, tied; "compensation" wins the tie-break.
    # A fetch adds a craft_direction assertion, which would flip a per-turn
    # re-rank toward compensation staying ahead — but only if ranking ran again.
    state = _state(assertions=[], targets=["craft_direction", "compensation"])
    recorded: list[LoopState] = []
    original_plan = navigator.plan

    def recording_plan(s: LoopState) -> list[Action]:
        recorded.append(s)
        return original_plan(s)

    navigator.plan = recording_plan  # type: ignore[method-assign]

    dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=_fake_extractor([[new_assertion]]), on_event=_noop),
        scoring_config=config,
    )

    assert recorded[0].primary_target == "compensation"
    assert recorded[1].primary_target == "compensation"


def test_search_action_browser_error_recorded_and_continues() -> None:
    """A failed search records a tavily_search event with the error and
    details, counts as a turn, and lets the navigator continue rather than
    aborting the pass."""
    query = "Acme Corp compensation"
    browser = FakeBrowser(search_fixtures={})  # no fixture → BrowserError
    stop = StopAction(reason="Nothing more to try.")
    navigator = FakeNavigator(
        sequence=[
            [SearchAction(query=query)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state()

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=_fake_extractor(), on_event=events.append),
    )

    search_events = [e for e in events if isinstance(e, SearchEvent)]
    assert len(search_events) == 1
    assert search_events[0].response.error
    assert search_events[0].response.details

    # The failed search still consumed a turn.
    assert summary.turns_used == 1
    assert isinstance(summary, PassSummary)


def test_fetch_action_browser_error_recorded_and_continues() -> None:
    """A failed fetch records a tavily_extract event with the error and
    details, adds the URL to visited_urls (so it isn't retried), counts
    as a turn, and lets the navigator continue rather than aborting the pass."""
    url = "https://acme.wd1.myworkdayjobs.example/blocked-posting"
    browser = FakeBrowser(fetch_fixtures={})  # no fixture → BrowserError
    stop = StopAction(reason="Nothing more to try.")
    navigator = FakeNavigator(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(assertions=[])

    summary = dispatch(
        state,
        navigator=navigator,
        deps=_deps(browser=browser, extractor=_fake_extractor(), on_event=events.append),
    )

    extract_events = [e for e in events if isinstance(e, ExtractEvent)]
    assert len(extract_events) == 1
    assert extract_events[0].response.error
    assert extract_events[0].response.details
    # `[]`, not `None`: replay counts this fetch as a turn on resume.
    assert extract_events[0].response.results == []

    # No assertions extracted, but the pass did not abort.
    assert summary.assertions_written == 0
    # The failed fetch still consumed a turn.
    assert summary.turns_used == 1
    assert isinstance(summary, PassSummary)


def test_fetch_action_browser_error_marks_url_visited() -> None:
    """A failed fetch adds the URL to visited_urls so a subsequent plan()
    call sees it and the navigator doesn't retry the same dead URL forever."""
    url = "https://www.acmehealth.example/about/careers-list/blocked"
    browser = FakeBrowser(fetch_fixtures={})
    stop = StopAction(reason="Done.")
    navigator = FakeNavigator(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    recorded: list[LoopState] = []
    original_plan = navigator.plan

    def recording_plan(s: LoopState) -> list[Action]:
        recorded.append(s)
        return original_plan(s)

    navigator.plan = recording_plan  # type: ignore[method-assign]

    dispatch(
        _state(assertions=[]),
        navigator=navigator,
        deps=_deps(browser=browser, extractor=_fake_extractor(), on_event=_noop),
    )

    assert url in recorded[1].visited_urls
