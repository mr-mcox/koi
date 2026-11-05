"""Live BAML adapter for the Survey function.
`query_assertion_history` is real: every
dimension's own assertions, rendered by `render_assertion_history`.
"""

from screen.baml_client.sync_client import BamlSyncClient, b
from screen.research.question import (
    ResearchQuestion,
    render_assertion_history,
    render_yield_summary,
)
from screen.research.state import LoopState


def _dimensions_text(state: LoopState) -> str:
    return ", ".join(state.targets)


class BAMLSurveyor:
    """Calls Survey via the generated BAML sync client."""

    def __init__(self, client: BamlSyncClient = b) -> None:
        self._client = client

    def survey(self, state: LoopState) -> ResearchQuestion:
        generated = self._client.Survey(
            company_name=state.company_name,
            opening_title=state.opening_title,
            rubric_text=state.rubric_text,
            dimensions=_dimensions_text(state),
            yield_summary=render_yield_summary(
                state.opening_id, state.pool_yield, state.target_stall_counts
            ),
            query_assertion_history=render_assertion_history(state.assertions, state.targets),
        )
        return ResearchQuestion(dimension=generated.dimension, question=generated.question)
