"""Tests for `JevVerdictProvider` I/O: calling Jev and parsing Noul answers into `JevRuling`.

Routing logic is tested separately in `tests/verdict/test_routing.py`.
"""

from __future__ import annotations

from typesafe_sdk import ChoiceAnswer, NoulAnswer, SystemOneResponse, Usage

from screen.score.loader import load_scoring_config
from screen.verdict.jev_verdict_provider import JevVerdictProvider
from screen.verdict.protocol import FewShotExample, JevRuling

_CONFIG = load_scoring_config()


class FakeTypeSafeClient:
    def __init__(self, response: SystemOneResponse) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, str], dict[str, object]]] = []

    def system_one(self, state: dict[str, str], questions: dict[str, object]) -> SystemOneResponse:
        self.calls.append((state, questions))
        return self.response


def _response(clear_winner: float, a_is_better: float) -> SystemOneResponse:
    return SystemOneResponse(
        model="test-model",
        usage=Usage(),
        answers={
            "clear_winner": NoulAnswer(noul=clear_winner),
            "a_is_better": NoulAnswer(noul=a_is_better),
        },
    )


def _few_shot() -> list[FewShotExample]:
    return [FewShotExample(digest_a="a", digest_b="b", outcome="tie")]


class TestJevVerdictProviderGetRuling:
    """Test the Jev I/O: parsing NoulAnswers into JevRuling."""

    def test_converts_noul_answers_to_ruling(self) -> None:
        client = FakeTypeSafeClient(_response(0.81, 0.72))
        provider = JevVerdictProvider(_CONFIG, client)

        ruling = provider.get_ruling("rubric", "digest a", "digest b", _few_shot())

        assert isinstance(ruling, JevRuling)
        assert ruling.clear_winner.p_true == 0.81
        assert ruling.a_is_better.p_true == 0.72

    def test_keeps_raw_p_true_on_false_answers(self) -> None:
        client = FakeTypeSafeClient(_response(0.3, 0.4))
        provider = JevVerdictProvider(_CONFIG, client)

        ruling = provider.get_ruling("rubric", "digest a", "digest b", _few_shot())

        assert ruling.clear_winner.p_true == 0.3
        assert ruling.a_is_better.p_true == 0.4

    def test_false_at_exactly_0_5_stays_raw(self) -> None:
        client = FakeTypeSafeClient(_response(0.5, 0.5))
        provider = JevVerdictProvider(_CONFIG, client)

        ruling = provider.get_ruling("rubric", "digest a", "digest b", _few_shot())

        assert ruling.clear_winner.p_true == 0.5
        assert ruling.a_is_better.p_true == 0.5

    def test_passed_state_to_jev(self) -> None:
        client = FakeTypeSafeClient(_response(0.9, 0.9))
        provider = JevVerdictProvider(_CONFIG, client)

        provider.get_ruling("my rubric", "digest a", "digest b", _few_shot())

        assert len(client.calls) == 1
        state, questions = client.calls[0]
        assert state["rubric"] == "my rubric"
        assert state["digest_a"] == "digest a"
        assert state["digest_b"] == "digest b"

    def test_rejects_non_noul_answers(self) -> None:
        response = SystemOneResponse(
            model="test-model",
            usage=Usage(),
            answers={
                "clear_winner": ChoiceAnswer(
                    choice="a", confidence=0.9, probabilities={"a": 1.0, "b": 0.0}
                ),
                "a_is_better": NoulAnswer(noul=0.9),
            },
        )
        provider = JevVerdictProvider(_CONFIG, FakeTypeSafeClient(response))

        try:
            provider.get_ruling("rubric", "digest a", "digest b", _few_shot())
        except ValueError as err:
            assert "non-Noul answer" in str(err)
        else:  # pragma: no cover
            raise AssertionError("Expected ValueError")
