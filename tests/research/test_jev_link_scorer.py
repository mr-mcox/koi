"""Tests for `JevLinkScorer` I/O: calling Jev and parsing Noul answers into
link relevance scores.
"""

from typesafe_sdk import NoulAnswer, SystemOneResponse, Usage

from screen.research.jev_link_scorer import JevLinkScorer
from screen.research.protocol import LinkScore


class FakeTypeSafeClient:
    def __init__(self, response: SystemOneResponse) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def system_one(
        self, state: dict[str, object], questions: dict[str, object]
    ) -> SystemOneResponse:
        self.calls.append((state, questions))
        return self.response


def _response(*nouls: float) -> SystemOneResponse:
    return SystemOneResponse(
        model="test-model",
        usage=Usage(),
        answers={f"link_{i}": NoulAnswer(noul=noul) for i, noul in enumerate(nouls)},
    )


class TestJevLinkScorer:
    def test_converts_noul_answers_to_link_scores(self) -> None:
        client = FakeTypeSafeClient(_response(0.81, 0.22))
        scorer = JevLinkScorer(client)

        scores = scorer.score_links(
            rubric_text="rubric",
            primary_target="compensation",
            research_question="What is total comp?",
            links=[("Blog", "https://example.com/blog"), ("Jobs", "https://example.com/jobs")],
        )

        assert scores == [
            LinkScore(url="https://example.com/blog", p_relevant=0.81),
            LinkScore(url="https://example.com/jobs", p_relevant=0.22),
        ]

    def test_passes_state_and_questions_to_jev(self) -> None:
        client = FakeTypeSafeClient(_response(0.9))
        scorer = JevLinkScorer(client)

        scorer.score_links(
            rubric_text="my rubric",
            primary_target="domain",
            research_question="What is the company domain?",
            links=[("Homepage", "https://example.com")],
        )

        assert len(client.calls) == 1
        state, questions = client.calls[0]
        assert state["rubric"] == "my rubric"
        assert state["primary_target"] == "domain"
        assert state["research_question"] == "What is the company domain?"
        assert state["links"] == [{"text": "Homepage", "url": "https://example.com"}]
        assert "link_0" in questions
        assert "Homepage" in questions["link_0"].instructions
        assert "https://example.com" in questions["link_0"].instructions
