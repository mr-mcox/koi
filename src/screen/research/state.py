"""Loop state types: LoopState (input) and PassSummary (output).
result is threaded forward through each dispatch cycle.

Budget fields land here so DecidePlan can see them. The dispatcher enforces the
turn cap (turns_used ≥ turn_budget → stop) alongside the first budget-consuming
action in the loop-search feature. A turn is one `search` or `fetch` action —
not `stop`/`decide_plan` — the operator-facing unit (docs/features/research-
resumability/bearing.md §Approach); token accounting was never wired to a real
meter and is dropped rather than kept as a second, unused budget.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from screen.research.context import FetchContext, SearchContext
from screen.types import Assertion, DimensionRuling


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
    turn_budget: Annotated[int, Field(ge=0)]
    turns_used: Annotated[int, Field(ge=0)]
    last_context: SearchContext | FetchContext | None = None
    visited_urls: list[str] = []
    prior_queries: list[str] = []
    # Operator pins for this opening. The research planner reads settledness to
    # raise or suppress urgency, but never writes rulings (domain-model.md wall).
    rulings: dict[str, DimensionRuling] = {}
    # All rubric targets the planner may be asked to research. Needed so an
    # unexamined target can outrank a thinly examined one in the uncertainty ranking.
    targets: list[str] = []
    # Sticky target: once selected, the planner stays on it until it either reports
    # no leads or hits the per-target action cap. Prevents search/fetch thrash when
    # a fetch on one target incidentally yields assertions about another.
    active_target: str | None = None
    active_target_actions: int = 0
    active_target_action_cap: int = 3
    # Transient directive computed by the dispatcher (or planner in tests) and
    # passed to DecidePlan so the model knows which target to focus this turn.
    primary_target: str | None = None


class PassSummary(BaseModel):
    """What the dispatcher reports after a complete pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_id: Annotated[str, Field(min_length=1)]
    company_id: Annotated[str, Field(min_length=1)]
    assertions_written: Annotated[int, Field(ge=0)]
    turns_used: Annotated[int, Field(ge=0)]
    stopped_reason: Annotated[str, Field(min_length=1)]
