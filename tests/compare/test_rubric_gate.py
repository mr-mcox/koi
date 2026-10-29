"""Acceptance tests for the fine-stage confidence gate: a verdict provider's ruling on a
candidate pair becomes a provisional win or tie `Comparison` only when the provider is
confident — an uncertain verdict produces no `Comparison`, so the pair surfaces to the
operator unchanged rather than auto-closing an uncertain judgment, but the raw verdict is
still returned so a caller can show the operator what Jev said. Wins are in scope
alongside ties."""

from screen.compare.rubric_gate import rubric_similarity_verdict
from screen.score.pairwise import Comparison
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


class _FixedRandom:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def random(self) -> float:
        return next(self._values)


class _UnsampledRandom:
    """Fails the test if the gate samples at all — the below-threshold and
    exactly-at-threshold paths must decide without consulting the rng."""

    def random(self) -> float:
        raise AssertionError("gate sampled rng on a path that must not sample")


def _run_gate(verdict: RubricVerdict, rng: _FixedRandom | _UnsampledRandom | None = None):
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
        rng=rng or _UnsampledRandom(),
    )


def test_confident_tie_becomes_a_provisional_tie() -> None:
    verdict = RubricVerdict(outcome="tie", confidence=0.95)
    result = _run_gate(verdict, rng=_FixedRandom([0.0]))

    assert result.verdict == verdict
    assert result.comparison == Comparison(
        winner="a", loser="b", tie=True, provenance="provisional", weight=0.95
    )


def test_confident_win_becomes_a_provisional_win_in_the_ruled_direction() -> None:
    """A win is directional — `outcome="a"` ties `a` as winner, `outcome="b"` reverses it.
    This is the win-propagation the offline tie-only kernel couldn't do."""
    result_a = _run_gate(RubricVerdict(outcome="a", confidence=0.92), rng=_FixedRandom([0.0]))
    assert result_a.comparison == Comparison(
        winner="a", loser="b", tie=False, provenance="provisional", weight=0.92
    )

    result_b = _run_gate(RubricVerdict(outcome="b", confidence=0.92), rng=_FixedRandom([0.0]))
    assert result_b.comparison == Comparison(
        winner="b", loser="a", tie=False, provenance="provisional", weight=0.92
    )


def test_uncertain_verdict_produces_no_comparison_but_keeps_the_raw_verdict() -> None:
    """Below threshold, there's no auto-ruled `Comparison` — but the raw verdict survives
    so the operator can see what Jev actually read (outcome and confidence) on a pair it
    couldn't settle, instead of it looking like Jev was never consulted."""
    verdict = RubricVerdict(outcome="tie", confidence=0.5)
    result = _run_gate(verdict)

    assert result.comparison is None
    assert result.verdict == verdict


def test_confidence_at_exactly_threshold_counts_as_confident() -> None:
    result = _run_gate(RubricVerdict(outcome="tie", confidence=0.9))

    assert result.comparison is not None
    assert result.comparison == Comparison(
        winner="a", loser="b", tie=True, provenance="provisional", weight=0.9
    )


def test_high_confidence_verdict_can_be_sampled_out() -> None:
    verdict = RubricVerdict(outcome="tie", confidence=0.95)
    result = _run_gate(verdict, rng=_FixedRandom([0.99]))

    assert result.verdict == verdict
    assert result.comparison is None
