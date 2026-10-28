"""Protocol surface for assertion classification providers.

Any object satisfying `AssertionClassifier` can be injected wherever a Jev assertion
classification is needed. The live adapter (TypeSafe's System One model) and test fakes
both satisfy it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

AssertionFit = Literal["Poor", "Mixed", "Strong"]


@dataclass(frozen=True)
class AssertionClassification:
    """A classification provider's ruling on one assertion: fit, is_relevant, and
    calibrated confidence scores for each judgment."""

    fit: AssertionFit
    confidence: float
    is_relevant: bool
    relevance_confidence: float


@runtime_checkable
class AssertionClassifier(Protocol):
    """Classifies an unclassified assertion's fit and relevance against its target
    dimension's rubric text, which the classifier holds."""

    def classify(self, chunk: str, target: str) -> AssertionClassification: ...
