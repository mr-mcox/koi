"""BAML adapter: calls `DigestDimension` and returns its prose.

Mirrors `screen.extract.baml_extractor.BAMLExtractor`'s shape — a thin
bridge from the generated client to `DigesterProtocol`. Style constraints
(no Fit word, no bare number, no self-referential summary phrasing) are
carried by the `DigestDimension` prompt, not enforced in code here — no
reliable automated check exists yet; the operator tunes the prompt against
live output.
"""

import json

from screen.baml_client.sync_client import b
from screen.types import Assertion


class BAMLDigester:
    """Satisfies `DigesterProtocol`. Calls `DigestDimension` via the BAML sync client."""

    def digest_dimension(
        self,
        assertions: list[Assertion],
        rubric_text: str,
    ) -> str:
        assertions_json = json.dumps(
            [a.model_dump(mode="json") for a in assertions],
            indent=None,
        )
        return b.DigestDimension(
            assertions_json=assertions_json,
            rubric_text=rubric_text,
        )
