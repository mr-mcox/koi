"""Pydantic model for transcript events."""

from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal["tavily_extract", "tavily_search", "decide_plan"]


class TavilyExtractResult(TypedDict):
    """One scraped page from a tavily_extract call."""

    url: str
    raw_content: str


class TavilyExtractResponse(TypedDict, total=False):
    """Top-level response shape from a tavily_extract call."""

    results: list[TavilyExtractResult]
    failed_results: list[dict[str, Any]]


class TranscriptEvent(BaseModel):
    """A single event recorded while a tool call ran.

    Shape (ts, tool, request, response) is the stable core; new fields
    are added here (e.g. `tool_error`) rather than splitting the root model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: Annotated[datetime, Field(description="UTC ISO timestamp of event emission.")]
    tool: ToolName
    request: Annotated[dict[str, Any], Field(description="Tool request payload as a JSON object.")]
    response: Annotated[
        dict[str, Any], Field(description="Tool response payload as a JSON object.")
    ]
