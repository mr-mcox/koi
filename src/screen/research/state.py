"""Loop state types: LoopState (input) and PassSummary (output).
result is threaded forward through each dispatch cycle.

Budget fields land here so DecidePlan can see them. The dispatcher
enforces the search cap (searches_used ≥ search_budget → stop) alongside
the first budget-consuming action in the loop-search feature.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from screen.research.context import FetchContext, SearchContext
from screen.types import Assertion


class LoopState(BaseModel):
    """All inputs the dispatcher needs for one research pass.

    File-agnostic: the caller populates this from in-memory values;
    loop/ never reads from disk.
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
    search_budget: Annotated[int, Field(ge=0)]
    searches_used: Annotated[int, Field(ge=0)]
    token_budget: Annotated[int, Field(ge=0)]
    tokens_used: Annotated[int, Field(ge=0)]
    last_context: SearchContext | FetchContext | None = None
    visited_urls: list[str] = []
    prior_queries: list[str] = []


class PassSummary(BaseModel):
    """What the dispatcher reports after a complete pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_id: Annotated[str, Field(min_length=1)]
    company_id: Annotated[str, Field(min_length=1)]
    assertions_written: Annotated[int, Field(ge=0)]
    searches_used: Annotated[int, Field(ge=0)]
    tokens_used: Annotated[int, Field(ge=0)]
    stopped_reason: Annotated[str, Field(min_length=1)]
