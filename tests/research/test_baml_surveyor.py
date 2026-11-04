"""Unit tests for BAMLSurveyor's call shape — dimensions text, stub inputs,
and translating the generated `ResearchQuestion` to the domain type."""

from types import SimpleNamespace

from screen.research.baml_surveyor import BAMLSurveyor
from screen.research.question import NOT_YET_AVAILABLE, ResearchQuestion
from screen.research.state import LoopState
from tests.helpers import canned_assertion


def _state(**kwargs: object) -> LoopState:
    defaults: dict[str, object] = {
        "opening_id": "op-abc",
        "company_id": "co-xyz",
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "page_content": "Some posting text.",
        "url": "https://example.com/jobs/1",
        "rubric_text": "craft_direction: ...",
        "assertions": [canned_assertion()],
        "turn_budget": 5,
        "turns_used": 0,
        "targets": ["craft_direction", "compensation"],
    }
    defaults.update(kwargs)
    return LoopState(**defaults)  # type: ignore[arg-type]


def test_baml_surveyor_survey_calls_generated_client_with_stub_inputs() -> None:
    calls: list[dict[str, object]] = []

    def fake_survey(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(dimension="compensation", question="What is total comp?")

    surveyor = BAMLSurveyor(client=SimpleNamespace(Survey=fake_survey))
    question = surveyor.survey(_state())

    assert question == ResearchQuestion(dimension="compensation", question="What is total comp?")
    assert calls[0] == {
        "company_name": "Acme Corp",
        "opening_title": "Staff Software Engineer",
        "rubric_text": "craft_direction: ...",
        "dimensions": "craft_direction, compensation",
        "yield_summary": NOT_YET_AVAILABLE,
        "query_assertion_history": NOT_YET_AVAILABLE,
    }
