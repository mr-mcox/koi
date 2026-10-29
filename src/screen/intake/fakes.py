"""Hand-written fakes satisfying the intake layer's Protocol surfaces."""

from collections.abc import Iterable

from screen.types import IdentificationResult


class FakeIdentifier:
    """Satisfies `Identifier`. Pops canned results in order; repeats last when exhausted."""

    def __init__(self, results: Iterable[IdentificationResult]) -> None:
        self._results: list[IdentificationResult] = list(results)
        if not self._results:
            raise ValueError("FakeIdentifier requires at least one result")
        self._index = 0

    def identify_opening(self, page_content: str) -> IdentificationResult:
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return self._results[-1]
