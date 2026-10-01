"""Acceptance tests for the two-stage provisional-comparison pipeline: coarse `fastembed`
cosine filter finds candidate pairs, fine-stage Jev (or a fake) rules each one; a
confident verdict becomes a provisional win or tie `Comparison`, an uncertain one
produces nothing so the pair surfaces to the operator unchanged."""

from __future__ import annotations

import numpy as np

from screen.score.compare import Comparison
from screen.score.provisional_verdicts import provisional_verdicts
from screen.verdict.protocol import RubricVerdict


class FakeEmbedder:
    def __init__(self, vectors_by_text: dict[str, np.ndarray]) -> None:
        self._map = vectors_by_text

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._map[t] for t in texts])


class FakeVerdictProvider:
    """Returns a verdict looked up by the (digest_a, digest_b) pair passed in, so tests
    can drive different candidates to different outcomes."""

    def __init__(self, verdicts_by_digest_pair: dict[tuple[str, str], RubricVerdict]) -> None:
        self._map = verdicts_by_digest_pair

    def rule(
        self, rubric_text: str, digest_a: str, digest_b: str, few_shot_examples: list
    ) -> RubricVerdict:
        return self._map[(digest_a, digest_b)]


def test_confident_candidate_becomes_a_provisional_comparison() -> None:
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder({"da": same, "db": same})
    digests = {"location": {"a": "da", "b": "db"}}
    provider = FakeVerdictProvider({("da", "db"): RubricVerdict(outcome="tie", confidence=0.95)})

    verdicts = provisional_verdicts(
        digests,
        embedder,
        tau=0.85,
        rubric_text_by_target={"location": "rubric text"},
        few_shot_examples_by_target={},
        provider=provider,
        confidence_threshold=0.9,
    )

    assert set(verdicts) == {"location"}
    assert verdicts["location"] == [
        Comparison(winner="a", loser="b", tie=True, provenance="provisional", weight=0.95)
    ]


def test_uncertain_candidate_produces_no_comparison() -> None:
    """The pair clears the coarse cosine gate but Jev is uncertain — the pipeline emits
    nothing, not a fallback tie; the pair surfaces to the operator unchanged."""
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder({"da": same, "db": same})
    digests = {"location": {"a": "da", "b": "db"}}
    provider = FakeVerdictProvider({("da", "db"): RubricVerdict(outcome="tie", confidence=0.5)})

    verdicts = provisional_verdicts(
        digests,
        embedder,
        tau=0.85,
        rubric_text_by_target={"location": "rubric text"},
        few_shot_examples_by_target={},
        provider=provider,
        confidence_threshold=0.9,
    )

    assert "location" not in verdicts


def test_dissimilar_pair_never_reaches_jev() -> None:
    """A pair that doesn't clear the coarse cosine gate is never sent to the verdict
    provider at all — the fine stage only runs on survivors."""
    embedder = FakeEmbedder({"dc": np.array([1.0, 0.0, 0.0]), "dd": np.array([0.0, 1.0, 0.0])})
    digests = {"location": {"c": "dc", "d": "dd"}}

    class ExplodingProvider:
        def rule(self, *args: object, **kwargs: object) -> RubricVerdict:
            raise AssertionError("Jev should never be called for a dissimilar pair")

    verdicts = provisional_verdicts(
        digests,
        embedder,
        tau=0.85,
        rubric_text_by_target={"location": "rubric text"},
        few_shot_examples_by_target={},
        provider=ExplodingProvider(),
        confidence_threshold=0.9,
    )

    assert "location" not in verdicts


def test_confident_win_carries_direction_through_the_pipeline() -> None:
    same = np.array([1.0, 0.0, 0.0])
    embedder = FakeEmbedder({"da": same, "db": same})
    digests = {"location": {"a": "da", "b": "db"}}
    provider = FakeVerdictProvider({("da", "db"): RubricVerdict(outcome="b", confidence=0.93)})

    verdicts = provisional_verdicts(
        digests,
        embedder,
        tau=0.85,
        rubric_text_by_target={"location": "rubric text"},
        few_shot_examples_by_target={},
        provider=provider,
        confidence_threshold=0.9,
    )

    assert verdicts["location"] == [
        Comparison(winner="b", loser="a", tie=False, provenance="provisional", weight=0.93)
    ]
