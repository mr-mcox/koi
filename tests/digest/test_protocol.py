"""Tests for the digest module: Protocol seam and FakeDigester."""

import pytest

from screen.digest.fakes import FakeDigester
from screen.digest.protocol import DigesterProtocol
from tests.helpers import canned_assertion


def test_fake_digester_requires_at_least_one_result() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FakeDigester([])


def test_fake_digester_returns_results_in_order() -> None:
    fake = FakeDigester(["first digest", "second digest"])
    assert fake.digest_dimension([canned_assertion()], "rubric") == "first digest"
    assert fake.digest_dimension([canned_assertion()], "rubric") == "second digest"


def test_fake_digester_repeats_last_when_exhausted() -> None:
    fake = FakeDigester(["only digest"])
    fake.digest_dimension([canned_assertion()], "rubric")
    result = fake.digest_dimension([canned_assertion()], "rubric")
    assert result == "only digest"


def test_fake_digester_satisfies_protocol() -> None:
    fake = FakeDigester(["some digest"])
    assert isinstance(fake, DigesterProtocol)
