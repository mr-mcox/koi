"""Fine-stage confidence gate: given a verdict provider's ruling on a candidate pair,
emit a provisional win or tie `Comparison` only when the provider is confident
(unanimous) — below the confidence threshold, emit nothing so the pair surfaces to the
operator unchanged. An uncertain verdict is never auto-closed; there is no default
outcome for a pair the provider itself isn't sure about. The raw verdict rides along
regardless of confidence, so a caller can show the operator what Jev actually said on a
pair it couldn't settle — otherwise an uncertain read is indistinguishable from Jev never
having been asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from screen.score.compare import Comparison
from screen.verdict.protocol import FewShotExample, RubricVerdict, VerdictProvider


class RandomSource(Protocol):
    def random(self) -> float: ...


@dataclass(frozen=True)
class GateOutcome:
    """Jev's full read on a candidate pair. `verdict` is always populated — Jev was
    consulted to produce this outcome at all. `comparison` is `None` below the
    confidence threshold; the operator-facing surface renders `verdict` either way."""

    verdict: RubricVerdict
    comparison: Comparison | None


def _auto_commit_probability(confidence: float, threshold: float) -> float:
    """Linear ramp from the threshold up to certainty: a pair only just over the bar
    rarely auto-commits and keeps feeding calibration, a near-certain one almost always
    does. The only caller gates on `confidence > threshold`, and confidence is 0-1 by
    the `RubricVerdict` contract, so `threshold < 1.0` holds and the denominator is
    never zero."""
    return min(1.0, (confidence - threshold) / (1.0 - threshold))


def rubric_similarity_verdict(
    opening_a_id: str,
    opening_b_id: str,
    *,
    rubric_text: str,
    digest_a: str,
    digest_b: str,
    few_shot_examples: list[FewShotExample],
    provider: VerdictProvider,
    confidence_threshold: float,
    rng: RandomSource,
) -> GateOutcome:
    """Rule on one candidate pair. `comparison` is `None` when the provider's confidence
    is below threshold — there is no default verdict for an uncertain pair; the picker
    keeps surfacing it to the operator exactly as it would without the kernel.

    Above the threshold, the gate samples auto-commit probability so very confident pairs
    are more likely to be emitted while borderline ones still feed calibration.
    """
    verdict = provider.rule(rubric_text, digest_a, digest_b, few_shot_examples)
    if verdict.confidence < confidence_threshold:
        return GateOutcome(verdict=verdict, comparison=None)
    if verdict.confidence > confidence_threshold:
        if rng.random() >= _auto_commit_probability(verdict.confidence, confidence_threshold):
            return GateOutcome(verdict=verdict, comparison=None)
    if verdict.outcome == "tie":
        winner, loser, tie = opening_a_id, opening_b_id, True
    elif verdict.outcome == "a":
        winner, loser, tie = opening_a_id, opening_b_id, False
    else:
        winner, loser, tie = opening_b_id, opening_a_id, False
    comparison = Comparison(
        winner=winner,
        loser=loser,
        tie=tie,
        provenance="provisional",
        weight=verdict.confidence,
    )
    return GateOutcome(verdict=verdict, comparison=comparison)
