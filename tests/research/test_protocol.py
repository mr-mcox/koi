"""Tests for Planner structural typing and FakePlanner.
- FakePlanner satisfies Planner via runtime_checkable
- FakePlanner returns its configured action list unchanged
- default FakePlanner returns [StopAction()]
- FakePlanner in sequence mode advances per call and repeats last
"""

import pytest

from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.fakes import FakePlanner
from screen.research.protocol import Planner
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
        active_target_action_cap=5,
        turns_used=0,
    )


def test_fake_planner_satisfies_protocol() -> None:
    planner = FakePlanner()
    assert isinstance(planner, Planner)


def test_fake_planner_default_returns_stop() -> None:
    planner = FakePlanner()
    actions = planner.plan(_state())
    assert len(actions) == 1
    assert isinstance(actions[0], StopAction)


def test_fake_planner_configured_actions_returned_unchanged() -> None:
    stop = StopAction(reason="Configured reason.")
    planner = FakePlanner(sequence=[[stop]])
    actions = planner.plan(_state())
    assert actions == [stop]


def test_fake_planner_plan_called_multiple_times() -> None:
    """FakePlanner returns the same list on every call (stateless)."""
    planner = FakePlanner()
    first = planner.plan(_state())
    second = planner.plan(_state())
    assert first == second


# ---------------------------------------------------------------------------
# FakePlanner sequence mode
# ---------------------------------------------------------------------------


def test_fake_planner_sequence_mode_advances_per_call() -> None:
    stop1 = StopAction(reason="reason one")
    stop2 = StopAction(reason="reason two")
    stop3 = StopAction(reason="reason three")
    planner = FakePlanner(sequence=[[stop1], [stop2], [stop3]])
    assert planner.plan(_state()) == [stop1]
    assert planner.plan(_state()) == [stop2]
    assert planner.plan(_state()) == [stop3]


def test_fake_planner_sequence_mode_repeats_last_when_exhausted() -> None:
    stop = StopAction(reason="final")
    planner = FakePlanner(sequence=[[StopAction(reason="first")], [stop]])
    planner.plan(_state())  # index=0
    planner.plan(_state())  # index=1 (last)
    # All subsequent calls repeat the last.
    assert planner.plan(_state()) == [stop]
    assert planner.plan(_state()) == [stop]


def test_fake_planner_sequence_single_step_repeats() -> None:
    """A single-step sequence returns that step on every call."""
    stop = StopAction(reason="done")
    planner = FakePlanner(sequence=[[stop]])
    assert planner.plan(_state()) == [stop]
    assert planner.plan(_state()) == [stop]  # repeats last


def test_fake_planner_sequence_mode_with_action_types() -> None:
    search = SearchAction(query="q")
    fetch = FetchAction(url="https://example.com/x")
    stop = StopAction(reason="done")
    planner = FakePlanner(sequence=[[search], [fetch], [stop]])
    assert planner.plan(_state()) == [search]
    assert planner.plan(_state()) == [fetch]
    assert planner.plan(_state()) == [stop]


def test_fake_planner_empty_sequence_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        FakePlanner(sequence=[])
