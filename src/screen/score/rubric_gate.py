"""Fine-stage confidence gate: given a verdict provider's ruling on a candidate pair,
emit a provisional win or tie `Comparison` only when the provider is confident
(unanimous) — below the confidence threshold, emit nothing so the pair surfaces to the
operator unchanged. An uncertain verdict is never auto-closed; there is no default
outcome for a pair the provider itself isn't sure about.
"""

from __future__ import annotations

from screen.score.compare import Comparison
from screen.verdict.protocol import FewShotExample, VerdictProvider


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
) -> Comparison | None:
    """Rule on one candidate pair. `None` when the provider's confidence is below
    threshold — there is no default verdict for an uncertain pair; the picker keeps
    surfacing it to the operator exactly as it would without the kernel."""
    verdict = provider.rule(rubric_text, digest_a, digest_b, few_shot_examples)
    if verdict.confidence < confidence_threshold:
        return None
    if verdict.outcome == "tie":
        winner, loser, tie = opening_a_id, opening_b_id, True
    elif verdict.outcome == "a":
        winner, loser, tie = opening_a_id, opening_b_id, False
    else:
        winner, loser, tie = opening_b_id, opening_a_id, False
    return Comparison(
        winner=winner,
        loser=loser,
        tie=tie,
        provenance="provisional",
        weight=verdict.confidence,
    )
