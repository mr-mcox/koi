"""Hand-written fake satisfying `AssertionClassifier`.

Kept alongside the live adapter so tests never construct a `TypeSafeClient`.
"""

from __future__ import annotations

from collections.abc import Iterable

from screen.verdict.classification_protocol import AssertionClassification


class FakeAssertionClassifier:
    """Satisfies `AssertionClassifier`. Returns canned classifications in order,
    repeating the last one when exhausted — mirrors `FakeExtractor`."""

    def __init__(self, results: Iterable[AssertionClassification]) -> None:
        self._results: list[AssertionClassification] = list(results)
        if not self._results:
            raise ValueError("FakeAssertionClassifier requires at least one result")
        self._index = 0

    def classify(self, rubric_text: str, chunk: str, target: str) -> AssertionClassification:
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return self._results[-1]
