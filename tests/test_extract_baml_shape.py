"""Verify that the generated BAML Assertion type matches the hand-written domain type.

If field names diverge, `baml_extractor.py` will fail at runtime. This test
makes that a CI failure instead of a production surprise.
"""

from screen.baml_client.baml_client.types import Assertion as BAMLAssertion
from screen.baml_client.baml_client.types import Citation as BAMLCitation
from screen.types import Assertion, Citation

_ASSERTION_FIELDS = set(Assertion.model_fields.keys())
_CITATION_FIELDS = set(Citation.model_fields.keys())


def test_baml_assertion_fields_match_domain_type() -> None:
    """Generated BAML Assertion must have exactly the same field names as
    the hand-written screen.types.Assertion. Any divergence means
    baml_extractor.py's field-by-field copy is silently wrong."""
    baml_fields = set(BAMLAssertion.model_fields.keys())
    assert baml_fields == _ASSERTION_FIELDS, (
        f"BAML Assertion fields diverged from domain type.\n"
        f"In BAML only: {baml_fields - _ASSERTION_FIELDS}\n"
        f"In domain only: {_ASSERTION_FIELDS - baml_fields}\n"
        "Re-run `baml-cli generate` or update extract.baml to match."
    )


def test_baml_citation_fields_match_domain_type() -> None:
    """Same check for Citation."""
    baml_fields = set(BAMLCitation.model_fields.keys())
    assert baml_fields == _CITATION_FIELDS, (
        f"BAML Citation fields diverged from domain type.\n"
        f"In BAML only: {baml_fields - _CITATION_FIELDS}\n"
        f"In domain only: {_CITATION_FIELDS - baml_fields}\n"
        "Re-run `baml-cli generate` or update extract.baml to match."
    )
