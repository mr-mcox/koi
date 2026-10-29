from typing import Protocol, runtime_checkable

from screen.types import IdentificationResult


@runtime_checkable
class Identifier(Protocol):
    def identify_opening(self, page_content: str) -> IdentificationResult: ...


def identify_opening(page_content: str, *, identifier: Identifier) -> IdentificationResult:
    return identifier.identify_opening(page_content)
