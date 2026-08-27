"""Loop-state context types: SearchContext and FetchContext.

These record what the last browser action produced so the planner can
reason about what to source next. They live in loop/ — not in browser.py —
because they are loop-state types, not browser return types.

Dependency rule: this module must never import from screen.intake.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from screen.browser import SearchHit


class SearchContext(BaseModel):
    """Records the result of a search action.

    Zero hits is a valid outcome and is not an error; the planner decides
    whether to refine the query or give up.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: Annotated[str, Field(min_length=1)]
    hits: list[SearchHit]


class FetchContext(BaseModel):
    """Records the result of a fetch action.

    targets_added=[] is valid — a hub page with no scorable claims does not
    force a stop. The planner sees the empty list and decides what to do next.
    snippet is the first 500 chars of raw content (enough for link spotting).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: Annotated[str, Field(min_length=1)]
    targets_added: list[str]
    snippet: str
