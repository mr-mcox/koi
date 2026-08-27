from unittest.mock import MagicMock

import pytest

from screen.intake import baml_identifier
from screen.intake.baml_identifier import BAMLIdentifier
from screen.types import IdentificationResult


def test_baml_identifier_calls_sync_client_and_coerces(monkeypatch: pytest.MonkeyPatch) -> None:
    """BAMLIdentifier delegates to the generated sync client and returns the canonical type."""
    generated = MagicMock()
    generated.company_name = "Acme Health"
    generated.opening_title = "Staff Platform Engineer"
    generated.opening_notes = "platform ownership, ECS/EKS, Terraform"
    fake_b = MagicMock(IdentifyOpening=MagicMock(return_value=generated))
    monkeypatch.setattr(baml_identifier, "b", fake_b)

    identifier = BAMLIdentifier()
    result = identifier.identify_opening("page content")

    assert isinstance(result, IdentificationResult)
    assert result.company_name == "Acme Health"
    assert result.opening_title == "Staff Platform Engineer"
    assert result.opening_notes == "platform ownership, ECS/EKS, Terraform"
    fake_b.IdentifyOpening.assert_called_once_with(page_content="page content")
