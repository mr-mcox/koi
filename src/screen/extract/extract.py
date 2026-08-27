"""Pure function wrapper for assertion extraction.

`extract_assertions` is the seam the dispatcher calls.
It has no file I/O — that is the caller's responsibility.
"""

from screen.extract.protocol import ExtractorProtocol
from screen.types import Assertion


def extract_assertions(
    chunk: str,
    rubric_text: str,
    existing: list[Assertion],
    *,
    extractor: ExtractorProtocol,
) -> list[Assertion]:
    """Extract new assertions from `chunk` and return them.
    `existing` is passed through to the extractor. No file I/O here.
    """
    return extractor.extract_assertions(chunk, rubric_text, existing)
