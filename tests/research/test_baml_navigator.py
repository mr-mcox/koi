"""Unit tests for BAMLNavigator coercion and context-rendering logic.

BAMLNavigator._coerce is exercised directly to cover the error branch
without requiring a live BAML call.

last_context_text() is a pure function; it is tested with known inputs so
the criterion "produces correct strings for known inputs" is mechanically
verified.
"""

from types import SimpleNamespace

import pytest

from screen.browser import SearchHit
from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.baml_navigator import (
    BAMLNavigator,
    _coerce,
    _prior_queries_text,
    last_context_text,
)
from screen.research.context import FetchContext, SearchContext
from screen.research.state import LoopState
from screen.types import Assertion


class _FakeStop:
    tag = "stop"
    reason = "Done."


class _FakeFetch:
    tag = "fetch"
    url = "https://example.com/page"


class _FakeSearch:
    tag = "search"
    query = "Acme Corp staff engineer compensation 2024"


class _FakeUnknown:
    tag = "future_tag"
    reason = "Would need a new branch."


def _state(
    *,
    assertions: list[Assertion] | None = None,
    last_context: FetchContext | SearchContext | None = None,
    **kwargs: object,
) -> LoopState:
    # turn_budget/turns_used stay in LoopState (dispatcher's budget guard reads
    # them) but are not passed to DecidePlan itself — the dispatcher owns budget.
    defaults: dict[str, object] = {
        "opening_id": "op-abc",
        "company_id": "co-xyz",
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "page_content": "Some posting text.",
        "url": "https://example.com/jobs/1",
        "rubric_text": "craft_direction: ...",
        "assertions": assertions if assertions is not None else [],
        "turn_budget": 5,
        "turns_used": 0,
        "last_context": last_context,
    }
    defaults.update(kwargs)
    return LoopState(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _coerce
# ---------------------------------------------------------------------------


def test_coerce_stop_returns_stop_action() -> None:
    result = _coerce(_FakeStop())
    assert isinstance(result, StopAction)
    assert result.reason == "Done."
    assert result.tag == "stop"


def test_coerce_fetch_returns_fetch_action() -> None:
    result = _coerce(_FakeFetch())
    assert isinstance(result, FetchAction)
    assert result.url == "https://example.com/page"
    assert result.tag == "fetch"


def test_coerce_search_returns_search_action() -> None:
    result = _coerce(_FakeSearch())
    assert isinstance(result, SearchAction)
    assert result.query == "Acme Corp staff engineer compensation 2024"
    assert result.tag == "search"


def test_coerce_unknown_tag_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="future_tag"):
        _coerce(_FakeUnknown())


# ---------------------------------------------------------------------------
# last_context_text
# ---------------------------------------------------------------------------


def test_last_context_text_none_returns_empty() -> None:
    state = _state(last_context=None)
    assert last_context_text(state) == ""


def test_last_context_text_fetch_context_with_targets() -> None:
    ctx = FetchContext(
        url="https://levels.fyi/acme",
        targets_added=["compensation", "craft_direction"],
        snippet="Acme pays $400k TC",
    )
    state = _state(last_context=ctx)
    text = last_context_text(state)
    assert "https://levels.fyi/acme" in text
    assert "compensation" in text
    assert "craft_direction" in text


def test_last_context_text_fetch_context_no_targets() -> None:
    ctx = FetchContext(url="https://example.com/hub", targets_added=[], snippet="")
    state = _state(last_context=ctx)
    text = last_context_text(state)
    assert "https://example.com/hub" in text
    assert "(none)" in text


def test_last_context_text_search_context() -> None:
    hits: list[SearchHit] = [
        SearchHit(url="https://a.com", raw_content="a"),
        SearchHit(url="https://b.com", raw_content="b"),
    ]
    ctx = SearchContext(query="Acme staff salary", hits=hits)
    state = _state(last_context=ctx)
    text = last_context_text(state)
    assert "Acme staff salary" in text
    assert "2" in text


def test_last_context_text_search_context_with_no_hits_says_so() -> None:
    """An empty search must read as a dead end, not as a results list with nothing
    under it, so the navigator rephrases instead of looking for a hit to fetch."""
    ctx = SearchContext(query="Acme staff salary", hits=[])
    text = last_context_text(_state(last_context=ctx))
    assert text == "Last action: searched 'Acme staff salary'. Got 0 hits."


def test_last_context_text_search_context_lists_hit_urls_and_snippets() -> None:
    """A search hit's url/title/snippet must reach the navigator — without them
    fetch is never a legal next move and the navigator is stuck searching forever
    (the live trap: three searches on the same target, no fetch, no assertions)."""
    hits: list[SearchHit] = [
        SearchHit(
            url="https://levels.fyi/companies/acme",
            title="Levels.fyi",
            snippet="Staff engineer total comp at Acme ranges $380k–$450k TC.",
        ),
    ]
    ctx = SearchContext(query="Acme staff engineer compensation 2024", hits=hits)
    state = _state(last_context=ctx)
    text = last_context_text(state)
    assert "https://levels.fyi/companies/acme" in text
    assert "Staff engineer total comp at Acme ranges $380k" in text


# ---------------------------------------------------------------------------
# Composite uncertainty / primary target selection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _prior_queries_text
# ---------------------------------------------------------------------------


def test_prior_queries_text_empty_returns_none_marker() -> None:
    assert _prior_queries_text(_state(prior_queries=[])) == "(none)"


def test_prior_queries_text_joins_in_order() -> None:
    state = _state(prior_queries=["Acme salary", "Acme culture"])
    assert _prior_queries_text(state) == "Acme salary; Acme culture"


# ---------------------------------------------------------------------------
# BAMLNavigator.plan dispatches the generated DecidePlan call
# ---------------------------------------------------------------------------


class _FakeBamlStop:
    tag = "stop"
    reason = "Mock stop."


def test_baml_navigator_plan_passes_through_state_unchanged() -> None:
    """The navigator passes primary_target/research_question already set on
    LoopState straight through, never recomputing either."""
    calls: list[dict[str, object]] = []

    def fake_decide_plan(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return [_FakeBamlStop()]

    navigator = BAMLNavigator(client=SimpleNamespace(DecidePlan=fake_decide_plan))
    state = _state(
        primary_target="compensation",
        research_question="What is total comp?",
        prior_queries=["Acme Corp salary"],
    )
    actions = navigator.plan(state)
    assert len(actions) == 1
    assert actions[0].tag == "stop"
    assert calls[0] == {
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "rubric_text": "craft_direction: ...",
        "primary_target": "compensation",
        "research_question": "What is total comp?",
        "last_context_text": "",
        "prior_queries": "Acme Corp salary",
    }


def test_baml_navigator_plan_blank_when_unset() -> None:
    """A missing primary_target/research_question renders as an empty string
    rather than `None` reaching the BAML call — the dispatcher always sets
    both before calling plan() in production; this pins the direct-call shape
    tests rely on."""
    calls: list[dict[str, object]] = []

    def fake_decide_plan(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return [_FakeBamlStop()]

    navigator = BAMLNavigator(client=SimpleNamespace(DecidePlan=fake_decide_plan))
    navigator.plan(_state(primary_target=None, research_question=None))

    assert calls[0]["primary_target"] == ""
    assert calls[0]["research_question"] == ""
