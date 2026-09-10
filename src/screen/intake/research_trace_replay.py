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


def replay_research_trace(path: Path) -> TraceReplay:
    turns_used = 0
    visited_urls: list[str] = []
    prior_queries: list[str] = []

    for raw_line in read_research_trace(path):
        line = raw_line.strip()
        if not line:
            continue
        event = ResearchTraceEvent.model_validate_json(line)
        if event.tool == "tavily_search":
            turns_used = _fold_search_event(event, turns_used, prior_queries)
        elif event.tool == "tavily_extract":
            turns_used = _fold_extract_event(event, turns_used, visited_urls)

    return TraceReplay(
        turns_used=turns_used, visited_urls=visited_urls, prior_queries=prior_queries
    )
