"""Tests for the digest module: Protocol seam and FakeDigester."""

import pytest

from screen.digest.fakes import FakeDigester
from screen.digest.protocol import DigesterProtocol
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


def test_fake_digester_requires_at_least_one_result() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FakeDigester([])


def test_fake_digester_returns_results_in_order() -> None:
    fake = FakeDigester(["first digest", "second digest"])
    assert fake.digest_dimension([_assertion()], "rubric") == "first digest"
    assert fake.digest_dimension([_assertion()], "rubric") == "second digest"


def test_fake_digester_repeats_last_when_exhausted() -> None:
    fake = FakeDigester(["only digest"])
    fake.digest_dimension([_assertion()], "rubric")
    result = fake.digest_dimension([_assertion()], "rubric")
    assert result == "only digest"


def test_fake_digester_satisfies_protocol() -> None:
    fake = FakeDigester(["some digest"])
    assert isinstance(fake, DigesterProtocol)
