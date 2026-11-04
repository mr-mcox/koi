"""Tests for Navigator structural typing and FakeNavigator.
- FakeNavigator satisfies Navigator via runtime_checkable
- FakeNavigator returns its configured action list unchanged
- default FakeNavigator returns [StopAction()]
- FakeNavigator in sequence mode advances per call and repeats last
"""

import pytest

from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.fakes import FakeNavigator
from screen.research.protocol import Navigator
from screen.research.state import LoopState
from screen.types import Assertion, Citation


def _state() -> LoopState:
    citation = Citation(
        url="https://example.com/jobs/1",
        quote="Build and own the platform.",
        host="example.com",
        source_provenance="official",
        independent=False,
        source_date=None,
    )
    assertion = Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="Build and own the platform every engineer deploys on.",
        citations=[citation],
        created_at="2026-08-28T00:00:00Z",
    )
    return LoopState(
        opening_id="op-abc",
        company_id="co-xyz",
        company_name="Acme Corp",
        opening_title="Staff Software Engineer",
        page_content="Some posting text.",
        url="https://example.com/jobs/1",
        rubric_text="craft_direction: ...",
        assertions=[assertion],
        turn_budget=5,
        turns_used=0,
    )


def test_fake_navigator_satisfies_protocol() -> None:
    navigator = FakeNavigator()
    assert isinstance(navigator, Navigator)


def test_fake_navigator_default_returns_stop() -> None:
    navigator = FakeNavigator()
    actions = navigator.plan(_state())
    assert len(actions) == 1
    assert isinstance(actions[0], StopAction)


def test_fake_navigator_configured_actions_returned_unchanged() -> None:
    stop = StopAction(reason="Configured reason.")
    navigator = FakeNavigator(sequence=[[stop]])
    actions = navigator.plan(_state())
    assert actions == [stop]


def test_fake_navigator_plan_called_multiple_times() -> None:
    """FakeNavigator returns the same list on every call (stateless)."""
    navigator = FakeNavigator()
    first = navigator.plan(_state())
    second = navigator.plan(_state())
    assert first == second


# ---------------------------------------------------------------------------
# FakeNavigator sequence mode
# ---------------------------------------------------------------------------


def test_fake_navigator_sequence_mode_advances_per_call() -> None:
    stop1 = StopAction(reason="reason one")
    stop2 = StopAction(reason="reason two")
    stop3 = StopAction(reason="reason three")
    navigator = FakeNavigator(sequence=[[stop1], [stop2], [stop3]])
    assert navigator.plan(_state()) == [stop1]
    assert navigator.plan(_state()) == [stop2]
    assert navigator.plan(_state()) == [stop3]


def test_fake_navigator_sequence_mode_repeats_last_when_exhausted() -> None:
    stop = StopAction(reason="final")
    navigator = FakeNavigator(sequence=[[StopAction(reason="first")], [stop]])
    navigator.plan(_state())  # index=0
    navigator.plan(_state())  # index=1 (last)
    # All subsequent calls repeat the last.
    assert navigator.plan(_state()) == [stop]
    assert navigator.plan(_state()) == [stop]


def test_fake_navigator_sequence_single_step_repeats() -> None:
    """A single-step sequence returns that step on every call."""
    stop = StopAction(reason="done")
    navigator = FakeNavigator(sequence=[[stop]])
    assert navigator.plan(_state()) == [stop]
    assert navigator.plan(_state()) == [stop]  # repeats last


def test_fake_navigator_sequence_mode_with_action_types() -> None:
    search = SearchAction(query="q")
    fetch = FetchAction(url="https://example.com/x")
    stop = StopAction(reason="done")
    navigator = FakeNavigator(sequence=[[search], [fetch], [stop]])
    assert navigator.plan(_state()) == [search]
    assert navigator.plan(_state()) == [fetch]
    assert navigator.plan(_state()) == [stop]


def test_fake_navigator_empty_sequence_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        FakeNavigator(sequence=[])
