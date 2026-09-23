"""Tests for replaying a research trace into resumable state.

Reconstructs what a fresh LoopState needs to continue a pass rather than
restart it: turns_used, visited_urls, prior_queries. The trace's
`ToolName` vocabulary is closed (tavily_extract, tavily_search, decide_plan),
so replay is a fold over a fixed set of event shapes, not an open parse.
"""

from datetime import UTC, datetime
from pathlib import Path

from screen.intake.events import ResearchTraceEvent
from screen.intake.research_trace_io import append_line
from screen.intake.research_trace_replay import replay_research_trace


def _extract_event(url: str, raw_content: str = "content") -> ResearchTraceEvent:
    return ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="tavily_extract",
        request={"urls": [url]},
        response={"results": [{"url": url, "raw_content": raw_content}]},
    )


def _search_event(query: str) -> ResearchTraceEvent:
    return ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="tavily_search",
        request={"query": query},
        response={"results": []},
    )


def _decide_plan_event() -> ResearchTraceEvent:
    return ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="decide_plan",
        request={"turns_used": 0},
        response={"actions": [{"tag": "stop", "reason": "done"}]},
    )


def test_missing_trace_replays_to_zero_turns(tmp_path: Path) -> None:
    replay = replay_research_trace(tmp_path / "missing.jsonl")
    assert replay.turns_used == 0
    assert replay.visited_urls == []
    assert replay.prior_queries == []


def test_replay_counts_extract_and_search_as_turns(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    append_line(path, _extract_event("https://example.com/jobs/1").model_dump_json())
    append_line(path, _search_event("Acme comp").model_dump_json())
    append_line(path, _extract_event("https://levels.fyi/acme").model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 3


def test_replay_does_not_count_decide_plan_as_a_turn(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    append_line(path, _extract_event("https://example.com/jobs/1").model_dump_json())
    append_line(path, _decide_plan_event().model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 1


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
    """The intake extract failure path writes an `error` response with no
    `results` key; replay must not raise on it and must not count a visited URL."""
    path = tmp_path / "trace.jsonl"
    event = ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="tavily_extract",
        request={"urls": ["https://nowhere.example/"]},
        response={"error": "fake says: gone"},
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 0
    assert replay.visited_urls == []


def test_replay_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text("\n\n" + _search_event("Acme comp").model_dump_json() + "\n", encoding="utf-8")

    replay = replay_research_trace(path)
    assert replay.turns_used == 1


def test_replay_ignores_extract_results_with_no_url(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    event = ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="tavily_extract",
        request={"urls": ["https://nowhere.example/"]},
        response={"results": [{"raw_content": "orphan"}]},
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 1
    assert replay.visited_urls == []


def test_replay_counts_search_with_no_query_field(tmp_path: Path) -> None:
    """A malformed/empty query still spends a turn, just doesn't add to prior_queries."""
    path = tmp_path / "trace.jsonl"
    event = ResearchTraceEvent(
        ts=datetime.now(UTC), tool="tavily_search", request={}, response={"results": []}
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 1
    assert replay.prior_queries == []


def test_replay_counts_failed_research_pass_fetch_as_a_turn(tmp_path: Path) -> None:
    """A dispatcher-recorded fetch failure carries an explicit empty `results` list
    alongside `error`/`details`,
    distinguishing it from the intake-time fatal failure (no `results` key
    at all). It still counts as a turn — the API call was made — but adds
    no visited URL since there is no result to fold."""
    path = tmp_path / "trace.jsonl"
    event = ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="tavily_extract",
        request={"urls": ["https://blocked.example/job/1"]},
        response={"error": "fetch failed", "details": {"failed_results": []}, "results": []},
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 1
    assert replay.visited_urls == []


def test_replay_counts_failed_research_pass_search_as_a_turn(tmp_path: Path) -> None:
    """A dispatcher-recorded search failure still spends a turn and does not
    add to prior_queries beyond the attempted query (existing fold already
    reads request['query'] regardless of response shape)."""
    path = tmp_path / "trace.jsonl"
    event = ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="tavily_search",
        request={"query": "Acme Corp culture"},
        response={"error": "search failed", "details": {"exception": "boom"}},
    )
    append_line(path, event.model_dump_json())

    replay = replay_research_trace(path)
    assert replay.turns_used == 1
    assert replay.prior_queries == ["Acme Corp culture"]


def _plan_event(
    active_target: str,
    targets_covered: list[str],
    target_assertion_counts: dict[str, int] | None = None,
) -> ResearchTraceEvent:
    request: dict[str, object] = {
        "active_target": active_target,
        "primary_target": active_target,
        "targets_covered": targets_covered,
    }
    if target_assertion_counts is not None:
        request["target_assertion_counts"] = target_assertion_counts
    return ResearchTraceEvent(
        ts=datetime.now(UTC),
        tool="decide_plan",
        request=request,
        response={"actions": [{"tag": "stop", "reason": "done"}]},
    )


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
            "stretch",
            ["compensation", "stretch"],
            target_assertion_counts={"compensation": 2, "stretch": 1},
        ).model_dump_json(),
    )
    replay = replay_research_trace(path)
    assert "compensation" not in replay.target_stalls


def test_replay_counts_based_stall_accumulates_across_repicks(tmp_path: Path) -> None:
    """Three separate re-picks of a stuck-at-one-assertion target accumulate
    three stalls, matching the S-curve's near-floor suppression at s=3."""
    path = tmp_path / "trace.jsonl"
    for other in ("domain", "extractive_business", "stretch"):
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
