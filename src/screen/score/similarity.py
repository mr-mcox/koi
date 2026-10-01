"""Coarse similarity gate: embed every opening's digest per target, compute pairwise
cosine, and return the pairs whose cosine exceeds τ — same-dimension only. This is the
bulk pre-filter ahead of the fine-stage Jev verdict (`screen.score.rubric_gate`): cheap,
local, vectorized, and it never constructs a `Comparison` or a weight itself — the
direction and weight of a provisional comparison come from Jev's verdict, not from
cosine. τ is operator-owned config, not a hidden constant (AGENTS.md
§measure-before-model).
"""

from __future__ import annotations

import numpy as np

from screen.embed.protocol import Embedder

_MIN_PAIR = 2


def _unit_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


def candidate_pairs(
    digests_by_target: dict[str, dict[str, str]],
    embedder: Embedder,
    tau: float,
) -> dict[str, list[tuple[str, str, float]]]:
    """Candidate pairs per target, keyed the way callers iterate targets one at a time.
    For each target, openings with a digest are embedded; every pair with cosine `s > τ`
    is a candidate, carrying the cosine itself for the fine stage to use if it wants.
    Targets with fewer than two digested openings produce no candidates."""
    out: dict[str, list[tuple[str, str, float]]] = {}
    for target, by_opening in digests_by_target.items():
        opening_ids = sorted(by_opening)
        if len(opening_ids) < _MIN_PAIR:
            continue
        texts = [by_opening[oid] for oid in opening_ids]
        vectors = _unit_normalize(embedder.embed(texts))
        pairs: list[tuple[str, str, float]] = []
        for i in range(len(opening_ids)):
            for j in range(i + 1, len(opening_ids)):
                s = float(vectors[i] @ vectors[j])
                if s > tau:
                    pairs.append((opening_ids[i], opening_ids[j], s))
        if pairs:
            out[target] = pairs
    return out
