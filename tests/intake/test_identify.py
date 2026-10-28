"""Wrapper and Protocol substitution tests."""

import inspect

import pytest

from screen.intake.fakes import FakeIdentifier
from screen.intake.identify import IdentifierProtocol, identify_opening
from screen.types import IdentificationResult


def test_identify_calls_protocol_with_page_content() -> None:
    fake = FakeIdentifier(
        [
            IdentificationResult(
                company_name="Acme Health",
                opening_title="Staff Platform Engineer",
                opening_notes="Public job posting",
            )
        ]
    )
    result = identify_opening("raw markup here", identifier=fake)
    assert isinstance(result, IdentificationResult)
    assert result.company_name == "Acme Health"
    assert result.opening_title == "Staff Platform Engineer"
    assert result.opening_notes == "Public job posting"


def test_identify_consumes_fake_in_order() -> None:
    canned = [
        IdentificationResult(company_name="A", opening_title="t1", opening_notes="n1"),
        IdentificationResult(company_name="A", opening_title="t2", opening_notes="n2"),
    ]
    fake = FakeIdentifier(canned)
    r1 = identify_opening("p1", identifier=fake)
    r2 = identify_opening("p2", identifier=fake)
    assert (r1.company_name, r1.opening_title) == ("A", "t1")
    assert (r2.company_name, r2.opening_title) == ("A", "t2")


def test_identify_accepts_any_protocol_implementation() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def identify_opening(self, page_content: str) -> IdentificationResult:
            self.calls.append(page_content)
            return IdentificationResult(
                company_name="Recorded",
                opening_title="R-title",
                opening_notes="R-notes",
            )

    rec = Recorder()
    result = identify_opening("call-marker", identifier=rec)
    assert result.company_name == "Recorded"
    assert rec.calls == ["call-marker"]


def test_identifier_protocol_has_typed_signature() -> None:
    """The Protocol's return type must match IdentificationResult — adapters rely on this."""
    method = IdentifierProtocol.identify_opening
    sig = inspect.signature(method)
    assert "page_content" in sig.parameters
    assert "IdentificationResult" in str(sig.return_annotation)


def test_fake_identifier_rejects_empty_results() -> None:
    with pytest.raises(ValueError, match="at least one result"):
        FakeIdentifier([])


def test_fake_identifier_repeats_last_when_exhausted() -> None:
    fake = FakeIdentifier(
        [IdentificationResult(company_name="A", opening_title="t1", opening_notes="n1")]
    )
    r1 = fake.identify_opening("p1")
    r2 = fake.identify_opening("p2")
    assert r1.opening_title == "t1"
    assert r2.opening_title == "t1"
