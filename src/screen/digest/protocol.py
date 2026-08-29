"""Protocol surface for dimension digesters.

Any object satisfying `DigesterProtocol` can be injected wherever a
digest is generated. The live adapter (`BAMLDigester`) and the fake
(`FakeDigester`) both satisfy it. Mirrors `screen.extract.protocol`.
"""

from typing import Protocol, runtime_checkable

from screen.types import Assertion


@runtime_checkable
class DigesterProtocol(Protocol):
    def digest_dimension(
        self,
        assertions: list[Assertion],
        rubric_text: str,
    ) -> str: ...
