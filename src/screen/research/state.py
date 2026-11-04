"""Research pass state: LoopState (input, threaded forward through each
dispatch cycle) and PassSummary (output, reported once per pass).

Budget fields live on LoopState so the Navigator can see them. The dispatcher
enforces the turn cap (`turns_used >= turn_budget` -> stop). A turn is one
`search` or `fetch` action, never `stop`/`decide_plan` — that is the
operator-facing unit, and the only budget the pass tracks.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from screen.research.context import FetchContext, SearchContext
from screen.types import Assertion


class LoopState(BaseModel):
    """All inputs the dispatcher needs for one research pass.

    File-agnostic: the caller populates this from in-memory values;
    `screen.research` never reads from disk.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_id: Annotated[str, Field(min_length=1)]
    company_id: Annotated[str, Field(min_length=1)]
    company_name: Annotated[str, Field(min_length=1)]
    opening_title: Annotated[str, Field(min_length=1)]
    page_content: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    rubric_text: Annotated[str, Field(min_length=1)]
    assertions: list[Assertion]
    turn_budget: Annotated[int, Field(ge=0)]
    turns_used: Annotated[int, Field(ge=0)]
    last_context: SearchContext | FetchContext | None = None
    visited_urls: list[str] = []
    prior_queries: list[str] = []
    # All rubric targets the Surveyor may choose among and the dispatcher
    # validates its answer against.
    targets: list[str] = []
    # Derived from the research trace on resume: how many contiguous runs on each
    # target ended without adding an assertion for that target. One of the
    # Surveyor's inputs (via a yield-rate summary) once that renderer lands.
    target_stall_counts: dict[str, int] = Field(default_factory=dict)
    # Set once per pass by the dispatcher from the Surveyor's answer, then held
    # fixed for every Navigator turn in the pass.
    primary_target: str | None = None
    research_question: str | None = None


class PassSummary(BaseModel):
    """What the dispatcher reports after a complete pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_id: Annotated[str, Field(min_length=1)]
    company_id: Annotated[str, Field(min_length=1)]
    assertions_written: Annotated[int, Field(ge=0)]
    turns_used: Annotated[int, Field(ge=0)]
    stopped_reason: Annotated[str, Field(min_length=1)]
