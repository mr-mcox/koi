"""Tests for loop/ domain types: LoopState, PassSummary, StopAction.

Pins the contracts the dispatcher and CLI rely on:
- frozen + extra=forbid on all three types
- round-trip serialization
- LoopState.model_copy threads state forward without mutation
- StopAction carries a non-empty reason string
"""

import pytest
from pydantic import ValidationError

from screen.loop.actions import StopAction
from screen.loop.context import FetchContext, SearchContext
from screen.loop.state import LoopState, PassSummary
from screen.types import Assertion, Citation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _citation() -> Citation:
    return Citation(
        url="https://example.com/jobs/1",
        quote="Build and own the platform.",
        host="example.com",
        source_provenance="official",
        independent=False,
        source_date=None,
    )


def _assertion() -> Assertion:
    return Assertion(
        target="stretch",
        fit="Strong",
        provenance="model_proposed",
        chunk="Build and own the platform every engineer deploys on.",
        citations=[_citation()],
        created_at="2026-08-28T00:00:00Z",
    )


def _loop_state(**kwargs: object) -> LoopState:
    defaults: dict[str, object] = {
        "opening_id": "op-abc",
        "company_id": "co-xyz",
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "page_content": "Some posting text.",
        "url": "https://example.com/jobs/1",
        "rubric_text": "stretch: ...",
        "assertions": [_assertion()],
        "search_budget": 5,
        "searches_used": 0,
        "token_budget": 50000,
        "tokens_used": 0,
    }
    defaults.update(kwargs)
    return LoopState(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LoopState
# ---------------------------------------------------------------------------


def test_loop_state_round_trips() -> None:
    state = _loop_state()
    restored = LoopState.model_validate_json(state.model_dump_json())
    assert restored == state


def test_loop_state_frozen() -> None:
    state = _loop_state()
    with pytest.raises((TypeError, ValidationError)):
        state.searches_used = 1  # type: ignore[misc]


def test_loop_state_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        LoopState(
            opening_id="op-abc",
            company_id="co-xyz",
            page_content="x",
            url="https://example.com",
            rubric_text="r",
            assertions=[],
            search_budget=5,
            searches_used=0,
            token_budget=50000,
            tokens_used=0,
            unexpected_field="boom",  # type: ignore[call-arg]
        )


def test_loop_state_model_copy_produces_new_instance() -> None:
    state = _loop_state()
    updated = state.model_copy(update={"searches_used": 1})
    assert updated.searches_used == 1
    assert state.searches_used == 0  # original unchanged
    assert updated is not state


def test_loop_state_new_fields_default_to_empty() -> None:
    """last_context, visited_urls, prior_queries all have clean defaults."""
    state = _loop_state()
    assert state.last_context is None
    assert state.visited_urls == []
    assert state.prior_queries == []


def test_loop_state_with_context_round_trips() -> None:
    ctx = SearchContext(query="Company A comp", hits=[])
    state = _loop_state(last_context=ctx, visited_urls=["https://x.com"], prior_queries=["q1"])
    restored = LoopState.model_validate_json(state.model_dump_json())
    assert restored == state


def test_loop_state_model_copy_updates_context() -> None:
    state = _loop_state()
    ctx = FetchContext(url="https://x.com", targets_added=["stretch"], snippet="excerpt")
    updated = state.model_copy(update={"last_context": ctx})
    assert updated.last_context == ctx
    assert state.last_context is None  # original unchanged


# ---------------------------------------------------------------------------
# PassSummary
# ---------------------------------------------------------------------------


def test_pass_summary_round_trips() -> None:
    summary = PassSummary(
        opening_id="op-abc",
        company_id="co-xyz",
        assertions_written=3,
        searches_used=0,
        tokens_used=0,
        stopped_reason="All rubric dimensions addressed.",
    )
    restored = PassSummary.model_validate_json(summary.model_dump_json())
    assert restored == summary


def test_pass_summary_frozen() -> None:
    summary = PassSummary(
        opening_id="op-abc",
        company_id="co-xyz",
        assertions_written=1,
        searches_used=0,
        tokens_used=0,
        stopped_reason="done",
    )
    with pytest.raises((TypeError, ValidationError)):
        summary.assertions_written = 99  # type: ignore[misc]


def test_pass_summary_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        PassSummary(
            opening_id="op-abc",
            company_id="co-xyz",
            assertions_written=1,
            searches_used=0,
            tokens_used=0,
            stopped_reason="done",
            unexpected="boom",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# StopAction
# ---------------------------------------------------------------------------


def test_stop_action_tag_is_stop() -> None:
    action = StopAction(reason="All dimensions covered.")
    assert action.tag == "stop"


def test_stop_action_round_trips() -> None:
    action = StopAction(reason="Budget exhausted.")
    restored = StopAction.model_validate_json(action.model_dump_json())
    assert restored == action


def test_stop_action_frozen() -> None:
    action = StopAction(reason="done")
    with pytest.raises((TypeError, ValidationError)):
        action.reason = "changed"  # type: ignore[misc]


def test_stop_action_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        StopAction(reason="done", surprise="boom")  # type: ignore[call-arg]
