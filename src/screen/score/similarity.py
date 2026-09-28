"""Similarity kernel: turn per-dimension digest embeddings into provisional tie
`Comparison`s, same-dimension only (→ scouting F11, F20).

For each target, embed every opening's digest, compute pairwise cosine, and emit a
provisional tie for each pair with cosine `s > τ` — weight graded `w(s) = clamp((s − s₀)/(1 − s₀), 0, 1)`
so a near-duplicate (s≈1) carries a full-strength tie and a barely-over-threshold pair carries
a weak one (→ scouting F10iii). τ and s₀ are operator-owned config, not hidden constants
(AGENTS.md §measure-before-model). The tie's `provenance` is `provisional` so the fit's
per-provenance beta weighs it less than an operator ruling (→ scouting F15α).
"""

from __future__ import annotations

import numpy as np

from screen.embed.protocol import Embedder
from screen.score.compare import Comparison

_MIN_PAIR = 2


def _unit_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


def _graded_weight(s: float, s0: float) -> float:
    """`w(s) = clamp((s − s₀)/(1 − s₀), 0, 1)` — 0 at and below s₀, 1 at cosine=1."""
    return max(0.0, min(1.0, (s - s0) / (1.0 - s0)))


def provisional_ties(
    digests_by_target: dict[str, dict[str, str]],
    embedder: Embedder,
    tau: float,
    s0: float,
) -> dict[str, list[Comparison]]:
    """Provisional similarity ties per target, keyed for `dimension_posteriors`'s
    `comparisons_by_target` argument. For each target, openings with a digest are
    embedded; every pair with cosine `s > τ` gets a provisional tie weighted by `w(s)`.
    Targets with fewer than two digested openings produce no ties."""
    out: dict[str, list[Comparison]] = {}
    for target, by_opening in digests_by_target.items():
        opening_ids = sorted(by_opening)
        if len(opening_ids) < _MIN_PAIR:
            continue
        texts = [by_opening[oid] for oid in opening_ids]
        vectors = _unit_normalize(embedder.embed(texts))
        ties: list[Comparison] = []
        for i in range(len(opening_ids)):
            for j in range(i + 1, len(opening_ids)):
                s = float(vectors[i] @ vectors[j])
                if s > tau:
                    ties.append(
                        Comparison(
                            winner=opening_ids[i],
                            loser=opening_ids[j],
                            tie=True,
                            provenance="provisional",
                            weight=_graded_weight(s, s0),
                        )
                    )
        if ties:
            out[target] = ties
    return out
