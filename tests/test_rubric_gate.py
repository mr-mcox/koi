"""Acceptance tests for the fine-stage confidence gate: a verdict provider's ruling on a
candidate pair becomes a provisional win or tie `Comparison` only when the provider is
confident — an uncertain verdict produces nothing, so the pair surfaces to the operator
unchanged rather than auto-closing an uncertain judgment. Wins are in scope alongside
ties."""

from __future__ import annotations

from screen.score.compare import Comparison
from screen.score.rubric_gate import rubric_similarity_verdict
from screen.verdict.protocol import RubricVerdict


class FakeVerdictProvider:
    """Returns a fixed verdict regardless of input, so tests control outcome and
    confidence directly."""

    def __init__(self, verdict: RubricVerdict) -> None:
        self._verdict = verdict

    def rule(
        self, rubric_text: str, digest_a: str, digest_b: str, few_shot_examples: list
    ) -> RubricVerdict:
        return self._verdict


def _run_gate(verdict: RubricVerdict):
    provider = FakeVerdictProvider(verdict)
    return rubric_similarity_verdict(
        "a",
        "b",
        rubric_text="rubric text",
        digest_a="digest a",
        digest_b="digest b",
        few_shot_examples=[],
        provider=provider,
        confidence_threshold=0.9,
    )


def test_confident_tie_becomes_a_provisional_tie() -> None:
    result = _run_gate(RubricVerdict(outcome="tie", confidence=0.95))

    assert result == Comparison(
        winner="a", loser="b", tie=True, provenance="provisional", weight=0.95
    )


def test_confident_win_becomes_a_provisional_win_in_the_ruled_direction() -> None:
    """A win is directional — `outcome="a"` ties `a` as winner, `outcome="b"` reverses it.
    This is the win-propagation the offline tie-only kernel couldn't do."""
    result_a = _run_gate(RubricVerdict(outcome="a", confidence=0.92))
    assert result_a == Comparison(
        winner="a", loser="b", tie=False, provenance="provisional", weight=0.92
    )

    result_b = _run_gate(RubricVerdict(outcome="b", confidence=0.92))
    assert result_b == Comparison(
        winner="b", loser="a", tie=False, provenance="provisional", weight=0.92
    )


def test_uncertain_verdict_produces_nothing() -> None:
    result = _run_gate(RubricVerdict(outcome="tie", confidence=0.5))

    assert result is None


def test_confidence_at_exactly_threshold_counts_as_confident() -> None:
    result = _run_gate(RubricVerdict(outcome="tie", confidence=0.9))

    assert result is not None
    assert result == Comparison(
        winner="a", loser="b", tie=True, provenance="provisional", weight=0.9
    )