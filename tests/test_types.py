"""Pydantic model tests — Company, Opening, IdentificationResult, Assertion, Citation.
Schema and Wall cross-references: `docs/architecture/domain-model.md`.
"""

import json
import uuid

import pytest
from pydantic import ValidationError

from screen.types import Assertion, AssertionRuling, Citation, Company, Opening


def _company(**overrides) -> dict:
    base = {
        "id": "acme-health",
        "name": "Acme Health",
        "created_at": "2026-08-22T12:00:00Z",
    }
    base.update(overrides)
    return base


def _opening(**overrides) -> dict:
    base = {
        "id": "acme-health--staff-platform-engineer-a54c1e",
        "company_id": "acme-health",
        "title": "Staff Platform Engineer",
        "url": "https://www.acmehealth.example/careers/staff-platform-engineer",
        "research_trace_id": "tx0123456789abcdef",
        "created_at": "2026-08-22T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_company_round_trip_minimum_valid() -> None:
    raw = _company()
    company = Company.model_validate(raw)
    dumped = company.model_dump(mode="json")
    assert json.loads(json.dumps(dumped)) == raw
    assert company.id == "acme-health"
    assert company.name == "Acme Health"


def test_opening_round_trip_minimum_valid() -> None:
    raw = _opening()
    opening = Opening.model_validate(raw)
    dumped = opening.model_dump(mode="json")
    assert json.loads(json.dumps(dumped)) == {**raw, "stage": "screening"}
    assert opening.company_id == "acme-health"
    assert opening.research_trace_id == "tx0123456789abcdef"
    assert opening.stage == "screening"


def test_opening_accepts_each_lifecycle_stage() -> None:
    for stage in ("screening", "pursuing", "applied", "closed"):
        opening = Opening.model_validate({**_opening(), "stage": stage})
        assert opening.stage == stage


def test_opening_rejects_unknown_stage() -> None:
    with pytest.raises(ValidationError):
        Opening.model_validate({**_opening(), "stage": "withdrawn"})


def test_company_rejects_unknown_field() -> None:
    """Frozen schema, extra=forbid. Score-like names must be rejected at
    validation time (Wall 1/2)."""
    with pytest.raises(ValidationError):
        Company.model_validate({**_company(), "score": 7.5})


def test_opening_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Opening.model_validate({**_opening(), "weighted_score": 6.7})


def test_company_is_frozen() -> None:
    company = Company.model_validate(_company())
    with pytest.raises(ValidationError):
        company.name = "Renamed Co"


def test_opening_is_frozen() -> None:
    opening = Opening.model_validate(_opening())
    with pytest.raises(ValidationError):
        opening.title = "Other Title"


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------


def _citation(**overrides: object) -> dict:  # type: ignore[type-arg]
    base = {
        "url": "https://example.com/jobs/42",
        "quote": "Build and own the platform.",
        "host": "example.com",
        "source_provenance": "official",
        "independent": True,
        "source_date": None,
    }
    base.update(overrides)
    return base


def _assertion(**overrides: object) -> dict:  # type: ignore[type-arg]
    base = {
        "id": "00000000-0000-0000-0000-000000000001",
        "target": "stretch",
        "fit": "Strong",
        "provenance": "model_proposed",
        "chunk": "10+ years in platform or infrastructure engineering.",
        "citations": [_citation()],
        "created_at": "2026-08-26T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_citation_round_trip_minimum_valid() -> None:
    raw = _citation()
    citation = Citation.model_validate(raw)
    dumped = citation.model_dump(mode="json")
    assert dumped["url"] == raw["url"]
    assert dumped["quote"] == raw["quote"]
    assert dumped["independent"] is True
    assert dumped["source_date"] is None


def test_assertion_round_trip_minimum_valid() -> None:
    raw = _assertion()
    assertion = Assertion.model_validate(raw)
    assert assertion.target == "stretch"
    assert assertion.fit == "Strong"
    assert assertion.provenance == "model_proposed"
    assert len(assertion.citations) == 1


def test_assertion_has_id() -> None:
    raw = _assertion()
    assertion = Assertion.model_validate(raw)
    assert assertion.id == raw["id"]
    assert len(assertion.id) >= 32


def test_assertion_id_defaults_to_uuid() -> None:
    raw = {k: v for k, v in _assertion().items() if k != "id"}
    assertion = Assertion.model_validate(raw)
    # uuid.UUID validates the string format; ValueError if malformed.
    uuid.UUID(assertion.id)


def test_assertion_ids_differ_by_default() -> None:
    raw = {k: v for k, v in _assertion().items() if k != "id"}
    a = Assertion.model_validate(raw)
    b = Assertion.model_validate(raw)
    assert a.id != b.id


def test_assertion_is_frozen() -> None:
    assertion = Assertion.model_validate(_assertion())
    with pytest.raises(ValidationError):
        assertion.fit = "Poor"  # type: ignore[misc]


def test_assertion_rejects_unknown_field() -> None:
    """Wall 1/2: no score or scoring field may land on an Assertion."""
    with pytest.raises(ValidationError):
        Assertion.model_validate({**_assertion(), "score": 7.5})


def test_assertion_rejects_weighted_score() -> None:
    with pytest.raises(ValidationError):
        Assertion.model_validate({**_assertion(), "weighted_score": 6.7})


def test_assertion_rejects_confidence_score() -> None:
    with pytest.raises(ValidationError):
        Assertion.model_validate({**_assertion(), "confidence_score": 0.8})


# ---------------------------------------------------------------------------
# Wall 3: closed Target Literal
# ---------------------------------------------------------------------------


def test_assertion_accepts_all_scoring_dimension_slugs() -> None:
    for slug in [
        "stretch",
        "schematic",
        "trajectory",
        "mission",
        "agentic",
        "compensation",
        "domain",
        "location",
        "internal_culture",
        "extractive_business",
    ]:
        a = Assertion.model_validate(_assertion(target=slug))
        assert a.target == slug


def test_assertion_accepts_non_scoring_obtainability() -> None:
    a = Assertion.model_validate(_assertion(target="non_scoring:obtainability"))
    assert a.target == "non_scoring:obtainability"


def test_assertion_rejects_bare_obtainability() -> None:
    """Wall 3: `obtainability` without the namespace prefix must be rejected."""
    with pytest.raises(ValidationError):
        Assertion.model_validate(_assertion(target="obtainability"))


def test_assertion_rejects_unknown_target() -> None:
    with pytest.raises(ValidationError):
        Assertion.model_validate(_assertion(target="made_up"))


def test_assertion_rejects_invalid_fit() -> None:
    with pytest.raises(ValidationError):
        Assertion.model_validate(_assertion(fit="7.5"))


def test_assertion_rejects_empty_citations() -> None:
    """citations must be non-empty (min_length=1)."""
    with pytest.raises(ValidationError):
        Assertion.model_validate(_assertion(citations=[]))


def test_citation_is_frozen() -> None:
    citation = Citation.model_validate(_citation())
    with pytest.raises(ValidationError):
        citation.url = "https://other.com"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AssertionRuling — operator's confirm/override verdict on one Assertion
# ---------------------------------------------------------------------------


def _assertion_ruling(**overrides: object) -> dict:  # type: ignore[type-arg]
    base = {
        "assertion_id": "00000000-0000-0000-0000-000000000001",
        "fit": "Strong",
        "created_at": "2026-08-29T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_assertion_ruling_round_trip_minimum_valid() -> None:
    raw = _assertion_ruling()
    ruling = AssertionRuling.model_validate(raw)
    assert ruling.assertion_id == raw["assertion_id"]
    assert ruling.fit == "Strong"


def test_assertion_ruling_id_defaults_to_uuid() -> None:
    ruling = AssertionRuling.model_validate(_assertion_ruling())
    uuid.UUID(ruling.id)


def test_assertion_ruling_is_frozen() -> None:
    ruling = AssertionRuling.model_validate(_assertion_ruling())
    with pytest.raises(ValidationError):
        ruling.fit = "Poor"  # type: ignore[misc]


def test_assertion_ruling_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        AssertionRuling.model_validate({**_assertion_ruling(), "score": 7.5})


def test_assertion_ruling_rejects_invalid_fit() -> None:
    with pytest.raises(ValidationError):
        AssertionRuling.model_validate(_assertion_ruling(fit="7.5"))
