"""Research trace event model tests, including the compatibility fixture:
every shape in `fixtures/trace_shapes.json` was written by some version of the
code and must keep loading (decisions.md E8)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from screen.research_trace.events import (
    DecidePlanEvent,
    ExtractEvent,
    ExtractRequest,
    ExtractResponse,
    ExtractResult,
    SearchEvent,
    parse_event,
)
from screen.research_trace.replay import replay_research_trace
from screen.research_trace.trace_io import append_line

_SHAPES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "trace_shapes.json").read_text(encoding="utf-8")
)


def _line(**overrides: object) -> str:
    base: dict[str, object] = {
        "ts": "2026-08-22T12:00:00Z",
        "tool": "tavily_extract",
        "request": {"urls": ["https://example.com/jobs/42"]},
        "response": {"results": []},
    }
    base.update(overrides)
    return json.dumps(base)


@pytest.mark.parametrize("shape", _SHAPES, ids=[s["shape"] for s in _SHAPES])
def test_every_recorded_shape_still_loads(shape: dict[str, Any]) -> None:
    event = parse_event(json.dumps(shape["line"]))
    assert event.tool == shape["line"]["tool"]


def test_replay_of_every_shape_folds_queries_and_visited_urls(tmp_path: Path) -> None:
    """Pins what each shape means on resume, not only that it parses."""
    path = tmp_path / "trace.jsonl"
    for shape in _SHAPES:
        append_line(path, json.dumps(shape["line"]))

    replay = replay_research_trace(path)

    assert replay.prior_queries == ["Example Co compensation", "Example Co culture"]
    assert replay.visited_urls == [
        "https://example.org/example-co",
        "https://example.com/jobs/2",
        "https://example.com/jobs/3",
        "https://example.com/jobs/4",
    ]


def test_parse_dispatches_on_tool() -> None:
    assert isinstance(parse_event(_line()), ExtractEvent)
    assert isinstance(
        parse_event(_line(tool="tavily_search", request={"query": "q"}, response={})),
        SearchEvent,
    )


def test_parse_rejects_unknown_tool() -> None:
    with pytest.raises(ValidationError):
        parse_event(_line(tool="tavily_pwn"))


def test_parse_rejects_unknown_event_field() -> None:
    with pytest.raises(ValidationError):
        parse_event(_line(side_effect="hello"))


def test_parse_validates_the_payload() -> None:
    """A payload whose field has the wrong type fails loudly rather than
    reading back as a default."""
    with pytest.raises(ValidationError):
        parse_event(
            _line(
                tool="decide_plan",
                request={
                    "opening_id": "op",
                    "company_id": "co",
                    "company_name": "Example Co",
                    "opening_title": "Engineer",
                    "prior_queries": [],
                    "visited_urls": [],
                    "targets_covered": [],
                    "target_assertion_counts": ["compensation"],
                    "last_context": None,
                },
                response={"actions": []},
            )
        )


def test_dumped_event_parses_back_equal() -> None:
    event = ExtractEvent(
        ts=datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC),
        request=ExtractRequest(urls=["https://example.com/jobs/42"]),
        response=ExtractResponse(
            results=[ExtractResult(url="https://example.com/jobs/42", raw_content="Body.")]
        ),
    )
    assert parse_event(event.model_dump_json()) == event


def test_event_is_frozen() -> None:
    event = parse_event(json.dumps(_SHAPES[0]["line"]))
    assert isinstance(event, DecidePlanEvent)
    with pytest.raises(ValidationError):
        event.ts = datetime.now(UTC)
