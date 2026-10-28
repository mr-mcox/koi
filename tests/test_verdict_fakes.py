"""Tests for `FakeAssertionClassifier` and the `AssertionClassifier` Protocol seam."""

from __future__ import annotations

import pytest

from screen.verdict.classification_protocol import AssertionClassification, AssertionClassifier
from screen.verdict.fakes import FakeAssertionClassifier


def _classification(**overrides: object) -> AssertionClassification:
    base: dict[str, object] = {
        "fit": "Strong",
        "confidence": 0.9,
        "is_relevant": True,
        "relevance_confidence": 0.9,
    }
    base.update(overrides)
    return AssertionClassification(**base)  # type: ignore[arg-type]


def test_fake_classifier_requires_at_least_one_result() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FakeAssertionClassifier([])


def test_fake_classifier_returns_results_in_order() -> None:
    c1 = _classification(fit="Poor")
    c2 = _classification(fit="Mixed")
    fake = FakeAssertionClassifier([c1, c2])
    assert fake.classify("chunk1", "craft_direction") == c1
    assert fake.classify("chunk2", "craft_direction") == c2


def test_fake_classifier_repeats_last_when_exhausted() -> None:
    c = _classification(fit="Strong")
    fake = FakeAssertionClassifier([c])
    fake.classify("chunk", "craft_direction")
    assert fake.classify("chunk", "craft_direction") == c


def test_fake_classifier_satisfies_protocol() -> None:
    fake = FakeAssertionClassifier([_classification()])
    assert isinstance(fake, AssertionClassifier)
