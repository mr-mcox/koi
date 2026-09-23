"""Unit tests for BAMLPlanner coercion and context-rendering logic.

BAMLPlanner._coerce is exercised directly to cover the error branch
without requiring a live BAML call.

last_context_text() is a pure function; it is tested with known inputs so
the criterion "produces correct strings for known inputs" is mechanically
verified.
"""

import pytest

from screen.browser import SearchHit
from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.baml_planner import (
    BAMLPlanner,
    _coerce,
    _prior_queries_text,
    _target_uncertainty,
    last_context_text,
    rank_targets,
    select_primary_target,
)
from screen.research.context import FetchContext, SearchContext
from screen.research.state import LoopState
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
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
        "rubric_text": "stretch: ...",
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


def test_last_context_text_search_context_lists_hit_urls_and_snippets() -> None:
    """A search hit's url/title/snippet must reach the planner — without them
    fetch is never a legal next move and the planner is stuck searching forever
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


def _config() -> ScoringConfig:
    config: ScoringConfig = load_scoring_config()
    return config


# ---------------------------------------------------------------------------
# _prior_queries_text
# ---------------------------------------------------------------------------


def test_prior_queries_text_empty_returns_none_marker() -> None:
    assert _prior_queries_text(_state(prior_queries=[])) == "(none)"


def test_prior_queries_text_joins_in_order() -> None:
    state = _state(prior_queries=["Acme salary", "Acme culture"])
    assert _prior_queries_text(state) == "Acme salary; Acme culture"


def test_rank_targets_prefers_unexamined_target() -> None:
    """An unexamined target outranks a target with one assertion."""
    config = _config()
    state = _state(
        assertions=[_assertion("stretch")],
        targets=["stretch", "compensation"],
    )
    ranked = rank_targets(state, config)
    assert ranked[0][0] == "compensation"


def test_rank_targets_falls_back_to_assertions() -> None:
    """When `state.targets` is empty, the ranking derives targets from whatever
    assertions exist."""
    config = _config()
    state = _state(
        assertions=[_assertion("stretch")],
        targets=[],
    )
    ranked = dict(rank_targets(state, config))
    assert "stretch" in ranked


def test_select_primary_target_stays_active_until_cap() -> None:
    config = _config()
    state = _state(
        assertions=[_assertion("stretch")],
        targets=["stretch", "compensation"],
        active_target="compensation",
        active_target_actions=1,
        active_target_action_cap=3,
    )
    assert select_primary_target(state, config) == "compensation"


def test_select_primary_target_releases_at_cap() -> None:
    config = _config()
    state = _state(
        assertions=[_assertion("stretch")],
        targets=["stretch", "compensation"],
        active_target="stretch",
        active_target_actions=3,
        active_target_action_cap=3,
    )
    # cap reached, re-rank; unexamined compensation wins
    assert select_primary_target(state, config) == "compensation"


def test_rank_targets_suppresses_stalled_target() -> None:
    """A target with prior unproductive runs ranks below an otherwise more
    attractive target: without suppression the unexamined stalled target would
    win, but the S-curve multiplier pushes it below the examined alternative."""
    config = _config()
    state = _state(
        assertions=[_assertion("compensation")],
        targets=["stretch", "compensation"],
        target_stall_counts={"stretch": 2},
    )
    ranked = rank_targets(state, config)
    assert ranked[0][0] == "compensation"
    # Sanity check the base signal: unexamined stretch outranks examined compensation.
    assert _target_uncertainty("stretch", n_by_target={}) > _target_uncertainty(
        "compensation", n_by_target={"compensation": 1.0}
    )


# ---------------------------------------------------------------------------
# BAMLPlanner.plan dispatches the generated DecidePlan call
# ---------------------------------------------------------------------------


class _FakeBamlStop:
    tag = "stop"
    reason = "Mock stop."


def test_baml_planner_plan_uses_state_primary_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The planner passes the primary_target already set on LoopState to the
    generated BAML client without recomputing it, using only the lean set of
    fields DecidePlan actually needs."""
    calls: list[dict[str, object]] = []

    def fake_decide_plan(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return [_FakeBamlStop()]

    monkeypatch.setattr("screen.research.baml_planner.b.DecidePlan", fake_decide_plan)

    planner = BAMLPlanner()
    state = _state(primary_target="compensation", prior_queries=["Acme Corp salary"])
    actions = planner.plan(state)
    assert len(actions) == 1
    assert actions[0].tag == "stop"
    assert calls[0] == {
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "rubric_text": "stretch: ...",
        "primary_target": "compensation",
        "last_context_text": "",
        "prior_queries": "Acme Corp salary",
    }


def test_baml_planner_plan_computes_primary_target_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a primary_target on state, the planner uses the config to
    select the top-ranked target before calling DecidePlan."""
    calls: list[dict[str, object]] = []

    def fake_decide_plan(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return [_FakeBamlStop()]

    monkeypatch.setattr("screen.research.baml_planner.b.DecidePlan", fake_decide_plan)

    planner = BAMLPlanner(config=_config())
    state = _state(
        assertions=[_assertion("stretch")],
        targets=["stretch", "compensation"],
    )
    actions = planner.plan(state)

    assert actions[0].tag == "stop"
    assert calls[0]["primary_target"] == "compensation"


def test_baml_planner_plan_fallback_to_stretch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If neither state nor the planner carries a config, the planner falls
    back to a hard-coded 'stretch' primary target so DecidePlan always has a
    value."""
    calls: list[dict[str, object]] = []

    def fake_decide_plan(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return [_FakeBamlStop()]

    monkeypatch.setattr("screen.research.baml_planner.b.DecidePlan", fake_decide_plan)

    planner = BAMLPlanner()
    state = _state(primary_target=None)
    planner.plan(state)

    assert calls[0]["primary_target"] == "stretch"
