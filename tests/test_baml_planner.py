"""Unit tests for BAMLPlanner coercion and context-rendering logic.

BAMLPlanner._coerce is exercised directly to cover the error branch
without requiring a live BAML call.

last_context_text() and coverage_summary() are pure functions; they are
tested with known inputs so the criterion "both produce correct strings
for known inputs" is mechanically verified.
"""

import pytest

from screen.browser import SearchHit
from screen.loop.actions import FetchAction, SearchAction, StopAction
from screen.loop.baml_planner import _coerce, _targets_covered, coverage_summary, last_context_text
from screen.loop.context import FetchContext, SearchContext
from screen.loop.state import LoopState
from screen.types import Assertion, Citation


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
    last_context: FetchContext | SearchContext | None = None,
) -> LoopState:
    return LoopState(
        opening_id="op-abc",
        company_id="co-xyz",
        company_name="Acme Corp",
        opening_title="Staff Software Engineer",
        page_content="Some posting text.",
        url="https://example.com/jobs/1",
        rubric_text="stretch: ...",
        assertions=assertions if assertions is not None else [],
        search_budget=5,
        searches_used=0,
        token_budget=50000,
        tokens_used=0,
        last_context=last_context,
    )


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
# coverage_summary
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _targets_covered
# ---------------------------------------------------------------------------


def test_targets_covered_no_assertions() -> None:
    state = _state(assertions=[])
    assert _targets_covered(state) == "domain"


def test_targets_covered_deduplicates() -> None:
    state = _state(assertions=[_assertion("stretch"), _assertion("stretch"), _assertion("peer")])
    result = _targets_covered(state)
    assert result == "stretch, peer, domain"


def test_targets_covered_domain_not_duplicated_when_actually_asserted() -> None:
    state = _state(assertions=[_assertion("domain")])
    assert _targets_covered(state) == "domain"


def test_coverage_summary_no_assertions() -> None:
    assert coverage_summary([]) == "(none)"


def test_coverage_summary_single_target() -> None:
    result = coverage_summary([_assertion("stretch"), _assertion("stretch")])
    assert result == "stretch(2)"


def test_coverage_summary_multiple_targets() -> None:
    assertions = [
        _assertion("stretch"),
        _assertion("peer"),
        _assertion("stretch"),
    ]
    result = coverage_summary(assertions)
    assert "stretch(2)" in result
    assert "peer(1)" in result


# ---------------------------------------------------------------------------
# last_context_text
# ---------------------------------------------------------------------------


def test_last_context_text_none_returns_empty() -> None:
    state = _state(last_context=None)
    assert last_context_text(state) == ""


def test_last_context_text_fetch_context_with_targets() -> None:
    ctx = FetchContext(
        url="https://levels.fyi/acme",
        targets_added=["compensation", "stretch"],
        snippet="Acme pays $400k TC",
    )
    state = _state(last_context=ctx)
    text = last_context_text(state)
    assert "https://levels.fyi/acme" in text
    assert "compensation" in text
    assert "stretch" in text


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
