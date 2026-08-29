"""Hand-written fake satisfying `DigesterProtocol`.

Kept in `digest/` (not `intake/fakes.py`) so the module boundary
between `intake/` and `digest/` stays clean, mirroring `extract/fakes.py`.
"""

from collections.abc import Iterable

from screen.types import Assertion


class FakeDigester:
    """Satisfies `DigesterProtocol`. Returns canned strings in order; repeats last when exhausted.

    `calls` counts invocations of `digest_dimension`, so tests can assert a
    cache hit skipped the (simulated) model call entirely.
    """

    def __init__(self, results: Iterable[str]) -> None:
        self._results: list[str] = list(results)
        if not self._results:
            raise ValueError("FakeDigester requires at least one result")
        self._index = 0
        self.calls = 0

    def digest_dimension(
        self,
        assertions: list[Assertion],
        rubric_text: str,
    ) -> str:
        self.calls += 1
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return self._results[-1]
