"""Replays a research trace file into the resumable working values that a
fresh `LoopState` needs to continue a pass instead of restarting one.

These are per-pass working values, computed from the transcript on demand —
never a second, independently-persisted copy that could drift from what the
trace says actually happened.
"""

from pathlib import Path
from typing import Annotated, Any, cast

from pydantic import BaseModel, ConfigDict, Field

from screen.intake.events import ResearchTraceEvent, TavilyExtractResponse
from screen.intake.research_trace_io import read_research_trace


class TraceReplay(BaseModel):
    """Resumable state folded out of a research trace's events.

    `turns_used` counts `tavily_search`/`tavily_extract` events only — a
    turn is one budget-consuming research action; `decide_plan`
    is the planner's own audit record, not a turn.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turns_used: Annotated[int, Field(ge=0)]
    visited_urls: list[str]
    prior_queries: list[str]
    # Contiguous unproductive active-target runs per target, reconstructed from
    # decide_plan events so a resume can suppress dead-end targets without a DB column.
    target_stalls: dict[str, int] = Field(default_factory=dict)


def _fold_search_event(event: ResearchTraceEvent, turns_used: int, prior_queries: list[str]) -> int:
    query = event.request.get("query")
    if query:
        prior_queries.append(str(query))
    return turns_used + 1


def _fold_extract_event(event: ResearchTraceEvent, turns_used: int, visited_urls: list[str]) -> int:
    """A `results` key present (even empty) means the fetch was attempted as
    part of a research pass and consumed a turn, whether it succeeded or
    failed. Its absence marks the
    fatal intake-time failure recorded before any Opening/budget exists,
    which is not a pass turn.
    """
    response = cast(TavilyExtractResponse, event.response)
    if "results" not in response:
        return turns_used
    results = response.get("results") or []
    for result in results:
        url = cast(dict[str, Any], result).get("url")
        if url:
            visited_urls.append(str(url))
    return turns_used + 1


def _run_target(event: ResearchTraceEvent) -> str | None:
    req = event.request
    return req.get("active_target") or req.get("primary_target")


def _counts(event: ResearchTraceEvent) -> dict[str, int] | None:
    """Per-target assertion count as of this decide_plan snapshot, or `None` if
    the trace predates `target_assertion_counts` (added alongside `targets_covered`
    in the dispatcher). Callers fall back to membership-only comparison for those
    older traces rather than guessing counts, which would manufacture false stalls
    for a target that grew past its first assertion between two runs.
    """
    raw = event.request.get("target_assertion_counts")
    if isinstance(raw, dict):
        return {str(k): int(v) for k, v in raw.items()}
    return None


def _covered(event: ResearchTraceEvent) -> set[str]:
    return set(event.request.get("targets_covered") or [])


def _segment_target_runs(
    plans: list[tuple[int, ResearchTraceEvent]],
) -> list[tuple[int, int, str | None]]:
    """Group contiguous decide_plan events that share the same active target."""
    runs: list[tuple[int, int, str | None]] = []
    if not plans:
        return runs
    start = 0
    current_target = _run_target(plans[0][1])
    for i in range(1, len(plans)):
        t = _run_target(plans[i][1])
        if t != current_target:
            runs.append((start, i - 1, current_target))
            start = i
            current_target = t
    runs.append((start, len(plans) - 1, current_target))
    return runs


def _is_stall_by_counts(target: str, start: dict[str, int], end: dict[str, int]) -> bool:
    return end.get(target, 0) <= start.get(target, 0)


def _is_stall_by_membership(target: str, start: set[str], end: set[str]) -> bool:
    """Membership-only fallback for traces without `target_assertion_counts`:
    a target already covered before the run is indistinguishable from one that
    grew during it, so this only catches a target newly covered by end — not
    re-picks of an already-covered target (that needs real counts).
    """
    return target not in end and target not in start


def _run_boundary_counts(
    plans: list[tuple[int, ResearchTraceEvent]], idx: int
) -> tuple[dict[str, int] | None, set[str]]:
    event = plans[idx][1]
    return _counts(event), _covered(event)


def _count_stalls(
    runs: list[tuple[int, int, str | None]],
    plans: list[tuple[int, ResearchTraceEvent]],
) -> dict[str, int]:
    """Count runs whose target showed no productive growth.

    Uses real per-target assertion counts when the trace carries them (a
    target already holding assertions is not exempt from stalling again);
    falls back to `targets_covered` membership for older traces, which can
    only detect a target that was never covered at all.
    """
    stalls: dict[str, int] = {}
    for run_index, (start_idx, end_idx, target) in enumerate(runs):
        if not target:
            continue
        end_source_idx = runs[run_index + 1][0] if run_index + 1 < len(runs) else end_idx
        start_counts, start_covered = _run_boundary_counts(plans, start_idx)
        end_counts, end_covered = _run_boundary_counts(plans, end_source_idx)
        if start_counts is not None and end_counts is not None:
            stalled = _is_stall_by_counts(target, start_counts, end_counts)
        else:
            stalled = _is_stall_by_membership(target, start_covered, end_covered)
        if stalled:
            stalls[target] = stalls.get(target, 0) + 1
    return stalls


def _fold_target_stalls(events: list[ResearchTraceEvent]) -> dict[str, int]:
    """Count unproductive contiguous runs per target from decide_plan events.
    A "run" is a maximal sequence of decide_plan events whose `active_target`
    (falling back to `primary_target`) is the same target. A run is a stall for
    that target when its assertion count is no higher by the run's end than it
    was at the run's start — whether or not the target already had assertions
    from an earlier, unrelated run.
    """
    plans = [(idx, event) for idx, event in enumerate(events) if event.tool == "decide_plan"]
    runs = _segment_target_runs(plans)
    return _count_stalls(runs, plans)


def replay_research_trace(path: Path) -> TraceReplay:
    turns_used = 0
    visited_urls: list[str] = []
    prior_queries: list[str] = []
    events: list[ResearchTraceEvent] = []

    for raw_line in read_research_trace(path):
        line = raw_line.strip()
        if not line:
            continue
        event = ResearchTraceEvent.model_validate_json(line)
        events.append(event)
        if event.tool == "tavily_search":
            turns_used = _fold_search_event(event, turns_used, prior_queries)
        elif event.tool == "tavily_extract":
            turns_used = _fold_extract_event(event, turns_used, visited_urls)

    return TraceReplay(
        turns_used=turns_used,
        visited_urls=visited_urls,
        prior_queries=prior_queries,
        target_stalls=_fold_target_stalls(events),
    )
