"""BAML generated client shape parity tests.

The BAML-generated `IdentificationResult` schema must match the
canonical `screen.types.IdentificationResult` field-for-field. If BAML
emits a different shape, the wrapper at `screen.intake.identify` would
silently coerce wrong fields to None. These tests pin the contract.
"""

from pydantic import BaseModel

from screen.baml_client.baml_client import types as baml_types
from screen.types import IdentificationResult


def test_baml_identification_result_has_required_fields() -> None:
    """The generated `IdentificationResult` carries the three fields
    the wrapper needs — `company_name`, `opening_title`, and
    `opening_notes`."""
    fields = set(IdentificationResult.model_fields.keys())
    assert fields == {"company_name", "opening_title", "opening_notes"}


def test_generated_identification_result_parity_with_canonical() -> None:
    """`baml_types.IdentificationResult` and
    `screen.types.IdentificationResult` agree on field names and
    types — the wrapper can construct a `BaseModel` instance from the
    generated client's `model_validate`."""
    canonical_fields = IdentificationResult.model_fields
    baml_fields = baml_types.IdentificationResult.model_fields
    assert set(canonical_fields.keys()) == set(baml_fields.keys())
    for key in canonical_fields:
        assert canonical_fields[key].annotation == baml_fields[key].annotation


def test_generated_identification_result_extends_basemodel() -> None:
    """BAML's Pydantic output is a `BaseModel` subclass; otherwise the
    canonical wrapper can't validate against it."""
    assert issubclass(baml_types.IdentificationResult, BaseModel)
