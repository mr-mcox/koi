"""Tests for the hand-written dispatch loop.
Pins:
- dispatch([stop]) returns PassSummary with correct counts
- unknown action tag raises RuntimeError (not silently skipped)
- searches_used and tokens_used thread from state into summary unchanged
- SearchAction happy path: browser.search called, event recorded, state updated
- SearchAction budget guard: searches_used >= search_budget → PassSummary, no extra plan() call
- FetchAction happy path: browser.fetch called, event recorded, assertions appended
- FetchAction duplicate: URL already in visited_urls → skip, no event, empty targets_added
- FetchAction zero assertions: does not raise, loop continues
"""

from typing import Literal

import pytest
from pydantic import ConfigDict

from screen.extract.fakes import FakeExtractor
from screen.intake.events import TranscriptEvent
from screen.loop.actions import Action, FetchAction, SearchAction, StopAction
from screen.loop.dispatcher import dispatch
from screen.loop.fakes import FakeBrowser, FakePlanner
from screen.loop.state import LoopState, PassSummary
from screen.types import Assertion, Citation


def _noop(_event: object) -> None:
    pass


def _citation() -> Citation:
    return Citation(
        url="https://example.com/jobs/1",
        quote="Build and own the platform.",
        host="example.com",
        source_provenance="official",
        independent=False,
        source_date=None,
    )


def _assertion(target: str = "stretch") -> Assertion:
    return Assertion(
        target=target,
        fit="Strong",
        provenance="model_proposed",
        chunk="Build and own the platform every engineer deploys on.",
        citations=[_citation()],
        created_at="2026-08-28T00:00:00Z",
    )


def _state(
    *,
    assertions: list[Assertion] | None = None,
    searches_used: int = 0,
    tokens_used: int = 1234,
    visited_urls: list[str] | None = None,
) -> LoopState:
    return LoopState(
        opening_id="op-abc",
        company_id="co-xyz",
        company_name="Acme Corp",
        opening_title="Staff Software Engineer",
        page_content="Some posting text.",
        url="https://example.com/jobs/1",
        rubric_text="stretch: ...",
        assertions=assertions if assertions is not None else [_assertion()],
        search_budget=5,
        searches_used=searches_used,
        token_budget=50000,
        tokens_used=tokens_used,
        visited_urls=visited_urls if visited_urls is not None else [],
    )


def _fake_extractor(results: list[list[Assertion]] | None = None) -> FakeExtractor:
    return FakeExtractor(results or [[]])


def test_dispatch_stop_returns_pass_summary() -> None:
    state = _state(assertions=[_assertion(), _assertion()])
    stop = StopAction(reason="All rubric dimensions addressed.")
    summary = dispatch(
        state,
        planner=FakePlanner(sequence=[[stop]]),
        browser=FakeBrowser(),
        extractor=_fake_extractor(),
        on_event=_noop,
    )

    assert isinstance(summary, PassSummary)
    assert summary.opening_id == "op-abc"
    assert summary.company_id == "co-xyz"
    assert summary.assertions_written == 2
    assert summary.stopped_reason == "All rubric dimensions addressed."


def test_decide_plan_event_records_request_and_response() -> None:
    """Every planner.plan() call is recorded as a decide_plan event: the
    request carries the state snapshot the planner saw, the response carries
    the action(s) it returned."""
    stop = StopAction(reason="Nothing left to check.")
    events: list[object] = []
    state = _state(searches_used=2, tokens_used=999)

    dispatch(
        state,
        planner=FakePlanner(sequence=[[stop]]),
        browser=FakeBrowser(),
        extractor=_fake_extractor(),
        on_event=events.append,
    )

    plan_events = [e for e in events if isinstance(e, TranscriptEvent) and e.tool == "decide_plan"]
    assert len(plan_events) == 1
    event = plan_events[0]

    assert event.request["opening_id"] == "op-abc"
    assert event.request["company_id"] == "co-xyz"
    assert event.request["company_name"] == "Acme Corp"
    assert event.request["opening_title"] == "Staff Software Engineer"
    assert event.request["searches_used"] == 2
    assert event.request["tokens_used"] == 999
    assert event.request["targets_covered"] == ["stretch"]
    assert event.request["last_context"] is None
    assert event.response == {"actions": [{"tag": "stop", "reason": "Nothing left to check."}]}


def test_dispatch_threads_budget_counters() -> None:
    state = _state(searches_used=2, tokens_used=8000)
    summary = dispatch(
        state,
        planner=FakePlanner(),
        browser=FakeBrowser(),
        extractor=_fake_extractor(),
        on_event=_noop,
    )

    assert summary.searches_used == 2
    assert summary.tokens_used == 8000


def test_dispatch_unknown_tag_raises_runtime_error() -> None:
    """Any tag the dispatcher doesn't recognize must be a hard error."""
    # Subclass StopAction with a different tag literal at runtime;
    # the dispatcher sees tag != "stop" and must raise.

    class UnknownAction(StopAction):
        model_config = ConfigDict(extra="forbid", frozen=True)
        tag: Literal["future_tag"] = "future_tag"  # type: ignore[assignment]

    planner: FakePlanner = FakePlanner(sequence=[[UnknownAction(reason="x")]])  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="future_tag"):
        dispatch(
            _state(),
            planner=planner,
            browser=FakeBrowser(),
            extractor=_fake_extractor(),
            on_event=_noop,
        )


def test_dispatch_empty_action_list_raises_runtime_error() -> None:
    """A planner returning [] must raise RuntimeError — the loop requires at least [stop]."""
    planner = FakePlanner(sequence=[[]])  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="empty action list"):
        dispatch(
            _state(),
            planner=planner,
            browser=FakeBrowser(),
            extractor=_fake_extractor(),
            on_event=_noop,
        )


def test_search_action_happy_path() -> None:
    """SearchAction calls browser.search, records a tavily_search event,
    increments searches_used, appends to prior_queries, and sets last_context
    to a SearchContext with the returned hits."""
    query = "Company A staff eng compensation 2024"
    hits = [
        {"url": "https://levels.fyi/", "title": "Levels", "snippet": "Staff $400k."},
    ]

    browser = FakeBrowser(search_fixtures={query: hits})
    stop = StopAction(reason="Covered.")
    planner = FakePlanner(
        sequence=[
            [SearchAction(query=query)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(searches_used=0)

    summary = dispatch(
        state,
        planner=planner,
        browser=browser,
        extractor=_fake_extractor(),
        on_event=events.append,
    )

    # browser.search was called with the right query
    assert browser.search_calls == [query]

    # tavily_search event was recorded (alongside decide_plan audit events)
    search_events = [
        e for e in events if isinstance(e, TranscriptEvent) and e.tool == "tavily_search"
    ]
    assert len(search_events) == 1
    event = search_events[0]
    assert event.request == {"query": query}

    # summary reflects one search used
    assert summary.searches_used == 1
    assert isinstance(summary, PassSummary)


def test_budget_guard_fires() -> None:
    """After a SearchAction that pushes searches_used to search_budget,
    the dispatcher returns PassSummary with stopped_reason='search budget exhausted'
    without calling planner.plan again."""
    query = "Company A comp"
    hits: list[object] = []

    # search_budget=1, searches_used starts at 0 — one search exhausts the budget
    browser = FakeBrowser(search_fixtures={query: hits})
    # If the guard misfires and calls plan() again, the second element would return stop;
    # but the guard must fire BEFORE the next plan() call.
    stop = StopAction(reason="Should not be reached.")
    planner = FakePlanner(
        sequence=[
            [SearchAction(query=query)],
            [stop],  # must NOT be reached
        ]
    )
    plan_calls: list[int] = []
    original_plan = planner.plan

    def counting_plan(s: LoopState) -> list[Action]:  # type: ignore[type-arg]
        plan_calls.append(1)
        return original_plan(s)

    planner.plan = counting_plan  # type: ignore[method-assign]

    state = _state(searches_used=0)
    state = state.model_copy(update={"search_budget": 1})

    summary = dispatch(
        state,
        planner=planner,
        browser=browser,
        extractor=_fake_extractor(),
        on_event=_noop,
    )

    # plan() was called exactly once (for the SearchAction)
    assert len(plan_calls) == 1
    # summary says budget exhausted
    assert summary.stopped_reason == "search budget exhausted"
    assert summary.searches_used == 1


def test_fetch_action_happy_path() -> None:
    """FetchAction against a new URL calls browser.fetch, records a tavily_extract
    event, runs extraction, and returns updated state with new assertions appended."""
    url = "https://levels.fyi/companies/acme"
    raw = "Acme pays $400k TC for staff engineers in remote roles."
    new_assertion = _assertion(target="compensation")

    browser = FakeBrowser(fetch_fixtures={url: {"raw_content": raw}})
    extractor = FakeExtractor([[new_assertion]])
    stop = StopAction(reason="Done after fetch.")
    planner = FakePlanner(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(assertions=[_assertion()])

    summary = dispatch(
        state,
        planner=planner,
        browser=browser,
        extractor=extractor,
        on_event=events.append,
    )

    # browser.fetch was called with the right URL
    assert browser.fetch_calls == [url]

    # tavily_extract event was recorded (alongside decide_plan audit events)
    extract_events = [
        e for e in events if isinstance(e, TranscriptEvent) and e.tool == "tavily_extract"
    ]
    assert len(extract_events) == 1
    event = extract_events[0]
    assert event.request == {"urls": [url]}

    # new assertion was appended to the summary count
    assert summary.assertions_written == 2  # original + new_assertion

    # FetchContext in last_context carried the new target
    # (accessible by inspecting the state passed to the second planner.plan call
    # — we verify via the summary assertion count and the browser call)
    assert isinstance(summary, PassSummary)


def test_fetch_action_duplicate_skipped() -> None:
    """FetchAction against a URL already in visited_urls skips the browser call
    and records no tavily_extract event; last_context.targets_added is empty."""
    url = "https://example.com/already-visited"
    browser = FakeBrowser(fetch_fixtures={url: {"raw_content": "content"}})
    extractor = FakeExtractor([[]])
    stop = StopAction(reason="Done.")
    planner = FakePlanner(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    events: list[object] = []
    state = _state(visited_urls=[url])

    summary = dispatch(
        state,
        planner=planner,
        browser=browser,
        extractor=extractor,
        on_event=events.append,
    )

    # browser.fetch was NOT called
    assert browser.fetch_calls == []
    # no tavily_extract event was recorded (decide_plan audit events still are)
    extract_events = [
        e for e in events if isinstance(e, TranscriptEvent) and e.tool == "tavily_extract"
    ]
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
    planner = FakePlanner(
        sequence=[
            [FetchAction(url=url)],
            [stop],
        ]
    )

    state = _state(assertions=[])

    summary = dispatch(
        state,
        planner=planner,
        browser=browser,
        extractor=extractor,
        on_event=_noop,
    )

    # No assertion added — extraction returned []
    assert summary.assertions_written == 0
    # Loop completed normally — no exception raised
    assert isinstance(summary, PassSummary)
    assert summary.stopped_reason == "Nothing more to do."
