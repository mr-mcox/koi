"""Pydantic event model tests."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from screen.intake.events import TranscriptEvent


def _event(**overrides) -> dict:
    base = {
        "ts": "2026-08-22T12:00:00Z",
        "tool": "tavily_extract",
        "request": {"urls": ["https://example.com/jobs/42"]},
        "response": {"results": [], "failed_results": []},
    }
    base.update(overrides)
    return base


def test_event_round_trip_minimum_valid() -> None:
    """All required fields, no extras. Pydantic constructs; .model_dump()
    returns the same dict back."""
    raw = _event()
    event = TranscriptEvent.model_validate(raw)
    assert event.tool == "tavily_extract"
    assert isinstance(event.ts, datetime)


def test_event_rejects_unknown_tool() -> None:
    """Wall: tool is Literal['tavily_extract','tavily_search']. A different
    string fails."""
    raw = _event(tool="tavily_pwn")
    with pytest.raises(ValidationError):
        TranscriptEvent.model_validate(raw)


def test_event_rejects_extra_fields() -> None:
    """Frozen on input. Adding an unmodeled key raises."""
    raw = _event(side_effect="hello")
    with pytest.raises(ValidationError):
        TranscriptEvent.model_validate(raw)


def test_event_serializes_to_jsonl_form() -> None:
    """`event.model_dump_json()` writes a single-line JSON. Wall 6
    expects one event per line; this is the contract."""
    event = TranscriptEvent.model_validate(_event())
    text = event.model_dump_json()
    parsed = json.loads(text)
    assert parsed["tool"] == "tavily_extract"


def test_event_is_frozen() -> None:
    """`frozen=True` prohibits attribute mutation. Prevents accidental
    in-place edits at runtime."""
    event = TranscriptEvent.model_validate(_event())
    with pytest.raises(ValidationError):
        event.tool = "tavily_search"


def test_event_accepts_tavily_search_tool() -> None:
    raw = _event(tool="tavily_search")
    event = TranscriptEvent.model_validate(raw)
    assert event.tool == "tavily_search"
