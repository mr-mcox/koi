"""Replays a research trace file into the resumable working values that a
fresh `LoopState` needs to continue a pass instead of restarting one.

These are per-pass working values, computed from the transcript on demand —
never a second, independently-persisted copy that could drift from what the
trace says actually happened.
"""

import re
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field

from screen.research_trace.events import DecidePlanEvent, ExtractEvent, SearchEvent, parse_event
from screen.research_trace.trace_io import read_research_trace
from screen.types import Target


class TraceReplay(BaseModel):
    """Resumable state folded out of a research trace's events.

    Turns are not replayed: each pass counts its own from zero, so the trace's
    running total has no reader.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    visited_urls: list[str]
    prior_queries: list[str]
    unvisited_links: list[tuple[str, str]] = Field(
        default_factory=list[tuple[str, str]]
    )  # (text, url)
    # Contiguous unproductive active-target runs per target, reconstructed from
    # decide_plan events so a resume can suppress dead-end targets without a DB column.
    target_stalls: dict[str, int] = Field(default_factory=dict)


def _run_target(event: DecidePlanEvent) -> str | None:
    req = event.request
    return req.active_target or req.primary_target


def _counts(event: DecidePlanEvent) -> dict[str, int] | None:
    """Callers fall back to membership-only comparison when this is `None`
    rather than guessing counts, which would manufacture false stalls for a
    target that grew past its first assertion between two runs.
    """
    return event.request.target_assertion_counts


def _covered(event: DecidePlanEvent) -> set[str]:
    return set(event.request.targets_covered)


def _segment_target_runs(
    plans: list[DecidePlanEvent],
) -> list[tuple[int, int, str | None]]:
    """Group contiguous decide_plan events that share the same active target."""
    runs: list[tuple[int, int, str | None]] = []
    if not plans:
        return runs
    start = 0
    current_target = _run_target(plans[0])
    for i in range(1, len(plans)):
        t = _run_target(plans[i])
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
    plans: list[DecidePlanEvent], idx: int
) -> tuple[dict[str, int] | None, set[str]]:
    event = plans[idx]
    return _counts(event), _covered(event)


def _count_stalls(
    runs: list[tuple[int, int, str | None]],
    plans: list[DecidePlanEvent],
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


class TargetYield(BaseModel):
    """How often research on one rubric dimension actually produced an assertion.

    `runs` and `yielded` are counted the same way `target_stalls` counts stalls
    (contiguous `decide_plan` runs sharing a target) — `yielded` is simply the
    non-stalled runs, so the two stay consistent by construction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: int
    yielded: int


def fold_target_yield(plans: list[DecidePlanEvent]) -> dict[str, TargetYield]:
    """Per-target run/yield counts, restricted to the current rubric's `Target`
    vocabulary. A trace may carry runs on a slug the rubric has since retired
    (e.g. `non_scoring:obtainability`) — those are dropped rather than
    reported, since a question step choosing among today's dimensions has no
    use for a rate on one that no longer exists.
    """
    current_targets = get_args(Target)
    runs = _segment_target_runs(plans)
    stalls = _count_stalls(runs, plans)
    run_counts: dict[str, int] = {}
    for _, _, target in runs:
        if not target or target not in current_targets:
            continue
        run_counts[target] = run_counts.get(target, 0) + 1
    return {
        target: TargetYield(runs=total, yielded=total - stalls.get(target, 0))
        for target, total in run_counts.items()
    }


def _fold_target_stalls(plans: list[DecidePlanEvent]) -> dict[str, int]:
    """Count unproductive contiguous runs per target from decide_plan events.
    A "run" is a maximal sequence of decide_plan events whose `active_target`
    (falling back to `primary_target`) is the same target. A run is a stall for
    that target when its assertion count is no higher by the run's end than it
    was at the run's start — whether or not the target already had assertions
    from an earlier, unrelated run.
    """
    runs = _segment_target_runs(plans)
    return _count_stalls(runs, plans)


def _extract_links(raw_content: str) -> list[tuple[str, str]]:
    """Markdown `[text](url)` links in a fetched page's stored content,
    http(s) only, fragment stripped (F5: the measured shape live traces hold).
    """
    links: list[tuple[str, str]] = []
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", raw_content):
        link_text: str = match.group(1).strip()
        url: str = match.group(2).split("#")[0]
        if url.startswith("http"):
            links.append((link_text, url))
    return links


def replay_research_trace(path: Path) -> TraceReplay:
    visited_urls: list[str] = []
    prior_queries: list[str] = []
    unvisited_links: list[tuple[str, str]] = []
    plans: list[DecidePlanEvent] = []
    for raw_line in read_research_trace(path):
        line = raw_line.strip()
        if not line:
            continue
        event = parse_event(line)
        if isinstance(event, DecidePlanEvent):
            plans.append(event)
        elif isinstance(event, SearchEvent):
            prior_queries.append(event.request.query)
        elif isinstance(event, ExtractEvent):
            for result in event.response.results or []:
                visited_urls.append(result.url)
                unvisited_links.extend(_extract_links(result.raw_content))
        # SurveyEvent: nothing to fold — the Surveyor runs fresh every pass (F20),
        # so its output isn't resumable state.
    visited_set = set(visited_urls)
    unvisited_links = [link for link in unvisited_links if link[1] not in visited_set]
    return TraceReplay(
        visited_urls=visited_urls,
        prior_queries=prior_queries,
        unvisited_links=unvisited_links,
        target_stalls=_fold_target_stalls(plans),
    )
