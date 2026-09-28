"""Acceptance tests for the similarity kernel: near-identical per-dimension digests
produce a provisional tie `Comparison`; dissimilar digests produce none. Uses a fake
embedder so the test never touches the live ONNX model."""

from __future__ import annotations

import numpy as np
import pytest

from screen.score.compare import Comparison
from screen.score.similarity import provisional_ties


class FakeEmbedder:
    """Returns a fixed vector per digest text, so tests control cosine directly."""

    def __init__(self, vectors_by_text: dict[str, np.ndarray]) -> None:
        self._map = vectors_by_text

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._map[t] for t in texts])


def test_near_identical_location_digests_get_a_provisional_tie() -> None:
    """Two openings whose `location` digests embed to the same unit vector (cosine 1.0 > τ)
    get one provisional tie on `location` — a tie, provenance `provisional`, weight graded
    to 1.0 at cosine=1.0."""
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder({"da": same, "db": same})
    digests = {"location": {"a": "da", "b": "db"}}

    ties = provisional_ties(digests, embedder, tau=0.85, s0=0.75)

    assert set(ties) == {"location"}
    location_ties = ties["location"]
    assert len(location_ties) == 1
    tie = location_ties[0]
    assert tie.tie is True
    assert tie.provenance == "provisional"
    assert {tie.winner, tie.loser} == {"a", "b"}
    # w(1.0) = clamp((1 - 0.75)/(1 - 0.25), 0, 1) = 1.0 — a perfect near-duplicate carries
    # full-strength weight.
    assert tie.weight == pytest.approx(1.0)


def test_dissimilar_location_digests_get_no_tie() -> None:
    """Two openings whose `location` digests embed to orthogonal vectors (cosine 0 < τ) get
    no provisional tie — dissimilarity is not evidence of a near-duplicate."""
    embedder = FakeEmbedder(
        {
            "dc": np.array([1.0, 0.0, 0.0]),
            "dd": np.array([0.0, 1.0, 0.0]),
        }
    )
    digests = {"location": {"c": "dc", "d": "dd"}}

    ties = provisional_ties(digests, embedder, tau=0.85, s0=0.75)

    assert ties.get("location", []) == []


def test_weight_ramps_with_similarity_above_threshold() -> None:
    """Above τ, the tie's weight grades with cosine via w(s) = clamp((s−s₀)/(1−s₀), 0, 1):
    a pair just over τ carries a weak tie, a near-duplicate carries a strong one."""
    # cosine = 0.9 -> w = clamp((0.9 - 0.75)/(1 - 0.75), 0, 1) = 0.15/0.25 = 0.6
    vec = np.array([0.9, 0.43589, 0.0])  # unit vector with ~0.9 cosine to [1,0,0]
    other = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder({"dx": other, "dy": vec})
    ties = provisional_ties({"location": {"x": "dx", "y": "dy"}}, embedder, tau=0.85, s0=0.75)

    tie = ties["location"][0]
    assert tie.weight == pytest.approx(0.6, abs=0.01)


def test_target_with_one_digested_opening_emits_no_tie() -> None:
    """A dimension with only one opening's digest has no pair to tie — the kernel skips it
    rather than emitting a degenerate single-opening tie."""
    embedder = FakeEmbedder({"da": np.array([1.0, 0.0, 0.0])})
    ties = provisional_ties({"location": {"a": "da"}}, embedder, tau=0.85, s0=0.75)
    assert ties.get("location", []) == []


def test_provisional_ties_are_same_dimension_only() -> None:
    """A `location`-similar pair emits a tie only on `location`, never on `mission` —
    similarity on one dimension is not evidence of similarity on another. The
    kernel embeds each target's digests independently."""
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder(
        {"da": same, "db": same, "dm-a": same, "dm-b": np.array([0.0, 1.0, 0.0])}
    )
    digests = {
        "location": {"a": "da", "b": "db"},  # near-identical location
        "mission": {"a": "dm-a", "b": "dm-b"},  # dissimilar mission
    }

    ties = provisional_ties(digests, embedder, tau=0.85, s0=0.75)

    assert set(ties) == {"location"}  # only the similar dimension gets a tie
    assert "mission" not in ties  # the dissimilar dimension is absent, not empty


def test_comparison_dataclass_round_trips_provenance_and_weight() -> None:
    """A provisional tie constructed by the kernel is a normal `Comparison` — provenance
    and weight survive a round trip through the dataclass (the fit consumes both)."""
    tie = Comparison(winner="a", loser="b", tie=True, provenance="provisional", weight=0.6)
    assert tie.provenance == "provisional"
    assert tie.weight == pytest.approx(0.6)
