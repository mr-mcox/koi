"""Tests for replaying a research trace into resumable state.

Reconstructs what a fresh LoopState needs to continue a pass rather than
restart it: visited_urls, prior_queries, target_stalls. The trace's
tool vocabulary is closed (tavily_extract, tavily_search, decide_plan — the
Navigate event's frozen wire literal),
so replay is a fold over a fixed set of event shapes, not an open parse.
"""

from datetime import UTC, datetime
from pathlib import Path

from screen.research_trace.events import (
    ExtractEvent,
    ExtractRequest,
    ExtractResponse,
    ExtractResult,
    NavigateEvent,
    NavigateRequest,
    NavigateResponse,
    SearchEvent,
    SearchRequest,
    SearchResponse,
)
from screen.research_trace.replay import fold_target_yield, replay_research_trace
from screen.research_trace.trace_io import append_line


def _extract_event(
    url: str, response: ExtractResponse | None = None, raw_content: str = "content"
) -> ExtractEvent:
    return ExtractEvent(
        ts=datetime.now(UTC),
        request=ExtractRequest(urls=[url]),
        response=(
            response
            if response is not None
            else ExtractResponse(results=[ExtractResult(url=url, raw_content=raw_content)])
        ),
    )


def _search_event(query: str, response: SearchResponse | None = None) -> SearchEvent:
    return SearchEvent(
        ts=datetime.now(UTC),
        request=SearchRequest(query=query),
        response=response if response is not None else SearchResponse(),
    )


def _plan_event(
    active_target: str | None = None,
    targets_covered: list[str] | None = None,
    target_assertion_counts: dict[str, int] | None = None,
) -> NavigateEvent:
    return NavigateEvent(
        ts=datetime.now(UTC),
        request=NavigateRequest(
            opening_id="op-1",
            company_id="co-1",
            company_name="Example Co",
            opening_title="Staff Engineer",
            active_target=active_target,
            primary_target=active_target,
            prior_queries=[],
            visited_urls=[],
            targets_covered=targets_covered or [],
            target_assertion_counts=target_assertion_counts,
            last_context=None,
        ),
        response=NavigateResponse(actions=[{"tag": "stop", "reason": "done"}]),
    )


def test_missing_trace_replays_to_empty_state(tmp_path: Path) -> None:
    replay = replay_research_trace(tmp_path / "missing.jsonl")
    assert replay.visited_urls == []
    assert replay.prior_queries == []


def test_replay_collects_visited_urls_in_order(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    append_line(path, _extract_event("https://example.com/jobs/1").model_dump_json())
    append_line(path, _extract_event("https://levels.fyi/acme").model_dump_json())

    replay = replay_research_trace(path)
    assert replay.visited_urls == ["https://example.com/jobs/1", "https://levels.fyi/acme"]


def test_replay_collects_prior_queries_in_order(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    append_line(path, _search_event("Acme comp").model_dump_json())
    append_line(path, _search_event("Acme culture").model_dump_json())

    replay = replay_research_trace(path)
    assert replay.prior_queries == ["Acme comp", "Acme culture"]


def test_replay_ignores_extract_with_no_results(tmp_path: Path) -> None:
    """Older failure records omit `results`; they visited no URL."""
    path = tmp_path / "trace.jsonl"
    event = _extract_event("https://nowhere.example/", ExtractResponse(error="fake says: gone"))
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.visited_urls == []


def test_replay_collects_markdown_links_from_raw_content(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    raw = (
        "See our [engineering blog](https://acme.com/blog) and "
        "[careers](https://acme.com/careers#openings)."
    )
    append_line(path, _extract_event("https://acme.com", raw_content=raw).model_dump_json())

    replay = replay_research_trace(path)
    assert replay.unvisited_links == [
        ("engineering blog", "https://acme.com/blog"),
        ("careers", "https://acme.com/careers"),
    ]


def test_replay_excludes_non_http_links(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    raw = "Email [us](mailto:jobs@acme.com) or see [site](https://acme.com/about)."
    append_line(path, _extract_event("https://acme.com", raw_content=raw).model_dump_json())

    replay = replay_research_trace(path)
    assert replay.unvisited_links == [("site", "https://acme.com/about")]


def test_replay_excludes_links_already_visited_in_the_trace(tmp_path: Path) -> None:
    """A link later fetched in the same trace is no longer a backlog candidate —
    it has already been explored, so re-surfacing it would waste a turn."""
    path = tmp_path / "trace.jsonl"
    raw = "See [careers](https://acme.com/careers)."
    append_line(path, _extract_event("https://acme.com", raw_content=raw).model_dump_json())
    append_line(path, _extract_event("https://acme.com/careers").model_dump_json())

    replay = replay_research_trace(path)
    assert replay.unvisited_links == []


def test_replay_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text("\n\n" + _search_event("Acme comp").model_dump_json() + "\n", encoding="utf-8")

    replay = replay_research_trace(path)
    assert replay.prior_queries == ["Acme comp"]


def test_replay_failed_fetch_adds_no_visited_url(tmp_path: Path) -> None:
    """A failed fetch has no result to fold. The dispatcher adds its URL to
    `visited_urls` in-pass, but a resume may try it again."""
    path = tmp_path / "trace.jsonl"
    event = _extract_event(
        "https://blocked.example/job/1",
        ExtractResponse(results=[], error="fetch failed", details={"failed_results": []}),
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.visited_urls == []


def test_replay_records_query_of_failed_search(tmp_path: Path) -> None:
    """The attempted query is a prior query whether or not the search succeeded."""
    path = tmp_path / "trace.jsonl"
    event = _search_event(
        "Acme Corp culture",
        SearchResponse(error="search failed", details={"exception": "boom"}),
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.prior_queries == ["Acme Corp culture"]


def test_replay_counts_single_target_stall(tmp_path: Path) -> None:
    """One unproductive active-target run is recorded as one stall for that target."""
    path = tmp_path / "trace.jsonl"
    append_line(path, _plan_event("agentic", []).model_dump_json())

    replay = replay_research_trace(path)
    assert replay.target_stalls == {"agentic": 1}


def test_replay_skips_stall_when_target_already_covered(tmp_path: Path) -> None:
    """A run on a target that already has assertions is not a new stall."""
    path = tmp_path / "trace.jsonl"
    append_line(path, _plan_event("agentic", ["agentic"]).model_dump_json())

    replay = replay_research_trace(path)
    assert replay.target_stalls == {}


def test_replay_skips_stall_when_later_run_covers_target(tmp_path: Path) -> None:
    """Cross-target crediting: a target covered during a later run is not stalled."""
    path = tmp_path / "trace.jsonl"
    append_line(path, _plan_event("agentic", []).model_dump_json())
    append_line(path, _plan_event("culture", ["agentic", "culture"]).model_dump_json())

    replay = replay_research_trace(path)
    assert replay.target_stalls == {}


def test_replay_accumulates_separate_stalls_for_same_target(tmp_path: Path) -> None:
    """Two separated unproductive runs on the same target count as two stalls."""
    path = tmp_path / "trace.jsonl"
    append_line(path, _plan_event("agentic", []).model_dump_json())
    append_line(path, _plan_event("culture", []).model_dump_json())
    append_line(path, _plan_event("agentic", []).model_dump_json())

    replay = replay_research_trace(path)
    assert replay.target_stalls == {"agentic": 2, "culture": 1}


def test_replay_flags_stall_on_already_covered_target_when_counts_present(tmp_path: Path) -> None:
    """The gap this closes: a target that already has one assertion from an
    earlier run must still stall if a later run re-picks it and adds nothing new
    — membership alone (`targets_covered`) can't see this, real counts can."""
    path = tmp_path / "trace.jsonl"
    append_line(
        path,
        _plan_event(
            "compensation",
            ["compensation"],
            target_assertion_counts={"compensation": 1},
        ).model_dump_json(),
    )

    replay = replay_research_trace(path)
    assert replay.target_stalls == {"compensation": 1}


def test_replay_does_not_flag_stall_when_counts_grew(tmp_path: Path) -> None:
    """A re-picked target whose count is higher by the next run's snapshot
    (a genuinely productive re-pick) is not a stall, even though it was
    already covered going in."""
    path = tmp_path / "trace.jsonl"
    append_line(
        path,
        _plan_event(
            "compensation",
            ["compensation"],
            target_assertion_counts={"compensation": 1},
        ).model_dump_json(),
    )
    append_line(
        path,
        _plan_event(
            "craft_direction",
            ["compensation", "craft_direction"],
            target_assertion_counts={"compensation": 2, "craft_direction": 1},
        ).model_dump_json(),
    )
    replay = replay_research_trace(path)
    assert "compensation" not in replay.target_stalls


def test_replay_counts_based_stall_accumulates_across_repicks(tmp_path: Path) -> None:
    """Three separate re-picks of a stuck-at-one-assertion target accumulate
    three stalls, matching the S-curve's near-floor suppression at s=3."""
    path = tmp_path / "trace.jsonl"
    for other in ("domain", "internal_culture", "craft_direction"):
        append_line(
            path,
            _plan_event(
                "compensation",
                ["compensation"],
                target_assertion_counts={"compensation": 1},
            ).model_dump_json(),
        )
        append_line(
            path,
            _plan_event(
                other,
                ["compensation"],
                target_assertion_counts={"compensation": 1},
            ).model_dump_json(),
        )

    replay = replay_research_trace(path)
    assert replay.target_stalls["compensation"] == 3


def test_fold_target_yield_counts_runs_and_yields_per_target() -> None:
    """One stalled run (membership-based: never covered) and one productive
    run (covered by its own end) on different targets."""
    plans = [
        _plan_event("compensation", []),
        _plan_event("agentic", ["agentic"]),
    ]
    yields = fold_target_yield(plans)
    assert yields["compensation"].runs == 1
    assert yields["compensation"].yielded == 0
    assert yields["agentic"].runs == 1
    assert yields["agentic"].yielded == 1


def test_fold_target_yield_drops_slugs_outside_current_target_vocabulary() -> None:
    """A retired slug (e.g. `non_scoring:obtainability`) from an old trace must
    not appear in the aggregate — only current rubric dimensions count."""
    plans = [
        _plan_event("non_scoring:obtainability", [], target_assertion_counts={}),
        _plan_event(
            "non_scoring:obtainability",
            ["non_scoring:obtainability"],
            target_assertion_counts={"non_scoring:obtainability": 1},
        ),
        _plan_event("agentic", [], target_assertion_counts={}),
    ]
    yields = fold_target_yield(plans)
    assert "non_scoring:obtainability" not in yields
    assert yields["agentic"].runs == 1


def test_fold_target_yield_empty_plans() -> None:
    assert fold_target_yield([]) == {}
