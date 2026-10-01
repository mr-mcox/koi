"""Acceptance tests for the coarse similarity gate: embeds every opening's digest per
target and returns the pairs whose cosine exceeds τ, same-dimension only. This is the
bulk pre-filter — candidates go to the fine-stage Jev verdict next; the coarse stage
itself never constructs a `Comparison` or a weight."""

from __future__ import annotations

import numpy as np
import pytest

from screen.score.similarity import candidate_pairs


class FakeEmbedder:
    """Returns a fixed vector per digest text, so tests control cosine directly."""

    def __init__(self, vectors_by_text: dict[str, np.ndarray]) -> None:
        self._map = vectors_by_text

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._map[t] for t in texts])


def test_near_identical_location_digests_are_a_candidate_pair() -> None:
    """Two openings whose `location` digests embed to the same unit vector (cosine 1.0 > τ)
    are one candidate pair on `location`, carrying the cosine itself — not a weight."""
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder({"da": same, "db": same})
    digests = {"location": {"a": "da", "b": "db"}}

    pairs = candidate_pairs(digests, embedder, tau=0.85)

    assert set(pairs) == {"location"}
    location_pairs = pairs["location"]
    assert len(location_pairs) == 1
    opening_a, opening_b, cosine = location_pairs[0]
    assert {opening_a, opening_b} == {"a", "b"}
    assert cosine == pytest.approx(1.0)


def test_dissimilar_location_digests_are_no_candidate() -> None:
    """Two openings whose `location` digests embed to orthogonal vectors (cosine 0 < τ) are
    not a candidate pair — dissimilarity isn't worth asking Jev about."""
    embedder = FakeEmbedder(
        {
            "dc": np.array([1.0, 0.0, 0.0]),
            "dd": np.array([0.0, 1.0, 0.0]),
        }
    )
    digests = {"location": {"c": "dc", "d": "dd"}}

    pairs = candidate_pairs(digests, embedder, tau=0.85)

    assert pairs.get("location", []) == []


def test_target_with_one_digested_opening_emits_no_candidate() -> None:
    """A dimension with only one opening's digest has no pair to consider — the coarse
    gate skips it rather than emitting a degenerate single-opening candidate."""
    embedder = FakeEmbedder({"da": np.array([1.0, 0.0, 0.0])})
    pairs = candidate_pairs({"location": {"a": "da"}}, embedder, tau=0.85)
    assert pairs.get("location", []) == []


def test_candidate_pairs_are_same_dimension_only() -> None:
    """A `location`-similar pair is a candidate only on `location`, never on `mission` —
    similarity on one dimension is not evidence of similarity on another. The coarse gate
    embeds each target's digests independently."""
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder(
        {"da": same, "db": same, "dm-a": same, "dm-b": np.array([0.0, 1.0, 0.0])}
    )
    digests = {
        "location": {"a": "da", "b": "db"},  # near-identical location
        "mission": {"a": "dm-a", "b": "dm-b"},  # dissimilar mission
    }

    pairs = candidate_pairs(digests, embedder, tau=0.85)

    assert set(pairs) == {"location"}  # only the similar dimension is a candidate
    assert "mission" not in pairs  # the dissimilar dimension is absent, not empty
