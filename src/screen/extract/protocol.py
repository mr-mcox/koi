"""Protocol surface for assertion extractors.

Any object satisfying `ExtractorProtocol` can be injected into
`extract_assertions`. The live adapter (`BAMLExtractor`) and the fake
(`FakeExtractor`) both satisfy it.
"""

from typing import Protocol, runtime_checkable

from screen.types import Assertion


@runtime_checkable
class ExtractorProtocol(Protocol):
    def extract_assertions(
        self,
        chunk: str,
        rubric_text: str,
        existing: list[Assertion],
    ) -> list[Assertion]: ...
