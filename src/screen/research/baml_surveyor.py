"""Live BAML adapter for the Survey function.

`yield_summary` and `query_assertion_history` are `NOT_YET_AVAILABLE` for
now; see that constant's docstring for why and what replaces it.
"""

from screen.baml_client.sync_client import BamlSyncClient, b
from screen.research.question import NOT_YET_AVAILABLE, ResearchQuestion
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
            yield_summary=NOT_YET_AVAILABLE,
            query_assertion_history=NOT_YET_AVAILABLE,
        )
        return ResearchQuestion(dimension=generated.dimension, question=generated.question)
