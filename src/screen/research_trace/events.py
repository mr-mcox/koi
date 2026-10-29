"""Pydantic models for research trace events and their per-tool payloads.

Traces are persisted JSONL read back on resume, so these models are the schema
between writers and readers across time as well as across files. The compatibility
rule (decisions.md E8): a new payload field is optional with a default that says what
its absence means; an existing field is never renamed or retyped.
`tests/research_trace/fixtures/trace_shapes.jsonl` holds one line per shape that
must keep loading.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from screen.browser import SearchHit


class _Payload(BaseModel):
    """Base for request and response payloads.

    Unknown keys are ignored, not rejected: older traces carry keys no longer
    modeled (pre-turn-budget `searches_used`, Tavily's raw `response_time`). Writers
    construct payloads by keyword, so pyright rejects a misspelled field on the
    write side.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)


class DecidePlanRequest(_Payload):
    """Snapshot of what the planner decided from. `replay` rebuilds stall state
    from `active_target`, `primary_target`, `targets_covered` and
    `target_assertion_counts`; the rest is audit trail.

    Targets are `str`, not `Target`: an old trace names targets since retired.
    """

    opening_id: str
    company_id: str
    company_name: str
    opening_title: str
    # Absent before turn budgets replaced search and token budgets. Counted from
    # zero each pass; older resumed passes started from the trace's running total.
    turns_used: int | None = None
    turn_budget: int | None = None
    # Absent before targeted passes; `None` also means no target was selected.
    primary_target: str | None = None
    active_target: str | None = None
    active_target_actions: int | None = None
    prior_queries: list[str]
    visited_urls: list[str]
    targets_covered: list[str]
    # `None` means the trace predates per-target counts; stall detection then
    # falls back to `targets_covered` membership.
    target_assertion_counts: dict[str, int] | None = None
    # A dumped `SearchContext` or `FetchContext`, which live in `research/` above
    # this layer. Audit only; nothing reads it back.
    last_context: dict[str, Any] | None


class DecidePlanResponse(_Payload):
    # Dumped `Action`s, which live in `research/`. Audit only.
    actions: list[dict[str, Any]]


class SearchRequest(_Payload):
    query: str


class SearchResponse(_Payload):
    """A failed search carries `error` and no results."""

    results: list[SearchHit] = Field(default_factory=list[SearchHit])
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict[str, Any])


class ExtractRequest(_Payload):
    urls: list[str]


class ExtractResult(_Payload):
    """One scraped page."""

    url: str
    raw_content: str


class ExtractResponse(_Payload):
    """A failed fetch carries `error` and empty `results`. Older failure
    records omit `results`, which loads as `None`."""

    results: list[ExtractResult] | None = None
    failed_results: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict[str, Any])


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: Annotated[datetime, Field(description="UTC ISO timestamp of event emission.")]


class DecidePlanEvent(_Event):
    """The planner's own audit record; not a budget-consuming turn."""

    tool: Literal["decide_plan"] = "decide_plan"
    request: DecidePlanRequest
    response: DecidePlanResponse


class SearchEvent(_Event):
    tool: Literal["tavily_search"] = "tavily_search"
    request: SearchRequest
    response: SearchResponse


class ExtractEvent(_Event):
    tool: Literal["tavily_extract"] = "tavily_extract"
    request: ExtractRequest
    response: ExtractResponse


type ResearchTraceEvent = Annotated[
    DecidePlanEvent | SearchEvent | ExtractEvent, Field(discriminator="tool")
]

_EVENT_ADAPTER: TypeAdapter[ResearchTraceEvent] = TypeAdapter(ResearchTraceEvent)


def parse_event(line: str) -> ResearchTraceEvent:
    """Validate one JSONL trace line, payload included."""
    return _EVENT_ADAPTER.validate_json(line)
