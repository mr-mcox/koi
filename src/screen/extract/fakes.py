"""Hand-written fakes satisfying `ExtractorProtocol`.

Kept in `extract/` (not `intake/fakes.py`) so the module boundary
between `intake/` and `extract/` stays clean.
"""

from collections.abc import Iterable

from screen.types import Assertion


class FakeExtractor:
    """Satisfies `ExtractorProtocol`. Returns canned results in order; repeats last when exhausted."""

    def __init__(self, results: Iterable[list[Assertion]]) -> None:
        self._results: list[list[Assertion]] = list(results)
        if not self._results:
            raise ValueError("FakeExtractor requires at least one result list")
        self._index = 0

    def extract_assertions(
        self,
        chunk: str,
        rubric_text: str,
        existing: list[Assertion],
    ) -> list[Assertion]:
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return self._results[-1]
