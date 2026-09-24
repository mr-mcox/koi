"""Tests for the extract module: Protocol seam, pure function, and FakeExtractor."""

import pytest

from screen.extract.extract import extract_assertions
from screen.extract.fakes import FakeExtractor
from screen.extract.protocol import ExtractorProtocol
from screen.types import Assertion, Citation


def _citation(**overrides: object) -> Citation:
    base = {
        "url": "https://example.com/jobs/42",
        "quote": "We use ECS/EKS and Terraform.",
        "host": "example.com",
        "source_provenance": "official",
        "independent": True,
        "source_date": None,
    }
    base.update(overrides)
    return Citation.model_validate(base)


def _assertion(**overrides: object) -> Assertion:
    base = {
        "target": "stretch",
        "fit": "Strong",
        "provenance": "model_proposed",
        "chunk": "Staff Platform Engineer, 10+ years required.",
        "citations": [_citation().model_dump(mode="json")],
        "created_at": "2026-08-26T12:00:00Z",
    }
    base.update(overrides)
    return Assertion.model_validate(base)


# ---------------------------------------------------------------------------
# FakeExtractor
# ---------------------------------------------------------------------------


def test_fake_extractor_requires_at_least_one_result() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FakeExtractor([])


def test_fake_extractor_returns_results_in_order() -> None:
    a1 = _assertion(target="stretch")
    a2 = _assertion(target="trajectory")
    fake = FakeExtractor([[a1], [a2]])
    assert fake.extract_assertions("chunk", "rubric", []) == [a1]
    assert fake.extract_assertions("chunk", "rubric", []) == [a2]


def test_fake_extractor_repeats_last_when_exhausted() -> None:
    a = _assertion(target="domain")
    fake = FakeExtractor([[a]])
    fake.extract_assertions("chunk", "rubric", [])
    # Second call beyond list: returns last
    result = fake.extract_assertions("chunk", "rubric", [])
    assert result == [a]


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


def test_fake_extractor_satisfies_protocol() -> None:
    """isinstance check against runtime_checkable Protocol."""
    fake = FakeExtractor([[_assertion()]])
    assert isinstance(fake, ExtractorProtocol)


# ---------------------------------------------------------------------------
# extract_assertions pure function
# ---------------------------------------------------------------------------


def test_extract_assertions_returns_extractor_output_unchanged() -> None:
    expected = [_assertion(target="trajectory")]
    fake = FakeExtractor([expected])
    result = extract_assertions("chunk", "rubric", [], extractor=fake)
    assert result == expected


def test_extract_assertions_passes_existing_through() -> None:
    """existing list is forwarded to the extractor; we verify via a spy."""
    existing = [_assertion(target="trajectory")]
    captured: list[list[Assertion]] = []

    class SpyExtractor:
        def extract_assertions(
            self, chunk: str, rubric_text: str, existing: list[Assertion]
        ) -> list[Assertion]:
            captured.append(existing)
            return []

    extract_assertions("chunk", "rubric", existing, extractor=SpyExtractor())
    assert captured == [existing]
