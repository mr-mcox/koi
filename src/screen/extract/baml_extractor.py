"""BAML adapter: bridges the generated `baml_client` types to `screen.types.Assertion`.

The generated types use the same field names as the hand-written domain types
(verified in `tests/test_extract_baml_shape.py`). Rather than copying fields
one by one, we dump the generated model and re-validate it as the domain type.
That makes the boundary check real: the closed `Target`/`Fit`/`Provenance`
Literals are validated here, not bypassed with a cast. The timestamp is owned
by the caller, not the model.
"""

import json
from datetime import UTC, datetime

from screen.baml_client.baml_client.sync_client import b
from screen.baml_client.baml_client.types import Assertion as BAMLAssertion
from screen.types import Assertion


def _to_assertion(a: BAMLAssertion, now: datetime) -> Assertion:
    """Re-validate the BAML output as the canonical domain type.

    `created_at` is overwritten with the caller's clock so the model never
    owns the timestamp. All other fields are validated by Pydantic, including
    the closed `target`/`fit`/`provenance` vocabularies.
    """
    dumped = a.model_dump()
    dumped["created_at"] = now
    return Assertion.model_validate(dumped)


class BAMLExtractor:
    """Satisfies `ExtractorProtocol`. Calls `ExtractAssertions` via the BAML sync client."""

    def extract_assertions(
        self,
        chunk: str,
        rubric_text: str,
        existing: list[Assertion],
    ) -> list[Assertion]:
        existing_json = json.dumps(
            [a.model_dump(mode="json") for a in existing],
            indent=None,
        )
        now = datetime.now(UTC)
        raw: list[BAMLAssertion] = b.ExtractAssertions(
            chunk=chunk,
            rubric_text=rubric_text,
            existing_assertions=existing_json,
        )
        return [_to_assertion(a, now) for a in raw]
