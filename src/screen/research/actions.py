"""Action types for the dispatch loop.
`Action` is a closed tagged union — no `Any` escape. Each tag must have
a matching dispatch branch; unrecognized tags raise `RuntimeError`.
`SearchAction` and `FetchAction` are recognized but their handlers raise
`RuntimeError` until the loop-search and loop-fetch features land.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StopAction(BaseModel):
    """Terminal action — the planner has nothing more to do."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tag: Literal["stop"] = "stop"
    reason: Annotated[str, Field(min_length=1)]


class SearchAction(BaseModel):
    """Direct the dispatcher to issue a web search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tag: Literal["search"] = "search"
    query: Annotated[str, Field(min_length=1)]


class FetchAction(BaseModel):
    """Direct the dispatcher to fetch a specific URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tag: Literal["fetch"] = "fetch"
    url: Annotated[str, Field(min_length=1)]


# Closed union. Loop-search and loop-fetch implement the search/fetch handlers.
Action = StopAction | SearchAction | FetchAction
