"""Two-stage provisional-comparison pipeline: the coarse cosine filter
(`screen.score.similarity.candidate_pairs`) finds pairs worth asking about; the fine
Jev gate (`screen.score.rubric_gate.rubric_similarity_verdict`) rules each one. A
confident verdict becomes a provisional win or tie `Comparison`; an uncertain one
produces nothing, so only survivors of *both* stages ever reach the fit — Jev is never
asked about a pair the coarse filter already ruled out.
"""

from __future__ import annotations

from screen.embed.protocol import Embedder
from screen.score.compare import Comparison
from screen.score.rubric_gate import rubric_similarity_verdict
from screen.score.similarity import candidate_pairs
from screen.verdict.protocol import FewShotExample, VerdictProvider


def provisional_verdicts(
    digests_by_target: dict[str, dict[str, str]],
    embedder: Embedder,
    *,
    tau: float,
    rubric_text_by_target: dict[str, str],
    few_shot_examples_by_target: dict[str, list[FewShotExample]],
    provider: VerdictProvider,
    confidence_threshold: float,
) -> dict[str, list[Comparison]]:
    """Provisional comparisons per target, keyed for `dimension_posteriors`'s
    `comparisons_by_target` argument. Coarse stage finds candidates (cosine > τ); fine
    stage rules each one and keeps only confident verdicts."""
    out: dict[str, list[Comparison]] = {}
    for target, pairs in candidate_pairs(digests_by_target, embedder, tau).items():
        rubric_text = rubric_text_by_target[target]
        few_shot_examples = few_shot_examples_by_target.get(target, [])
        by_opening = digests_by_target[target]
        verdicts: list[Comparison] = []
        for opening_a_id, opening_b_id, _cosine in pairs:
            comparison = rubric_similarity_verdict(
                opening_a_id,
                opening_b_id,
                rubric_text=rubric_text,
                digest_a=by_opening[opening_a_id],
                digest_b=by_opening[opening_b_id],
                few_shot_examples=few_shot_examples,
                provider=provider,
                confidence_threshold=confidence_threshold,
            )
            if comparison is not None:
                verdicts.append(comparison)
        if verdicts:
            out[target] = verdicts
    return out
