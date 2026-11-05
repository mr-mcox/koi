"""Unit tests for BAMLSurveyor's call shape — dimensions text, rendered
assertion history, the still-stubbed yield summary, and translating the
generated `ResearchQuestion` to the domain type."""

from types import SimpleNamespace

from screen.research.baml_surveyor import BAMLSurveyor
from screen.research.question import ResearchQuestion, render_yield_summary
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
    state = _state()
    question = surveyor.survey(state)

    assert question == ResearchQuestion(dimension="compensation", question="What is total comp?")
    call = calls[0]
    assert call["company_name"] == "Acme Corp"
    assert call["opening_title"] == "Staff Software Engineer"
    assert call["rubric_text"] == "craft_direction: ..."
    assert call["dimensions"] == "craft_direction, compensation"
    assert call["yield_summary"] == render_yield_summary(
        state.opening_id, state.pool_yield, state.target_stall_counts
    )


def test_baml_surveyor_renders_real_assertion_history_not_a_placeholder() -> None:
    """query_assertion_history is the real per-dimension render, across every
    dimension, unlike the Navigator's, which narrows to its one fixed target."""
    calls: list[dict[str, object]] = []

    def fake_survey(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(dimension="compensation", question="What is total comp?")

    surveyor = BAMLSurveyor(client=SimpleNamespace(Survey=fake_survey))
    comp_assertion = canned_assertion(target="compensation", chunk="Pays $400k TC.")
    surveyor.survey(
        _state(assertions=[comp_assertion], targets=["craft_direction", "compensation"])
    )

    history = calls[0]["query_assertion_history"]

    assert "Pays $400k TC." in history
    assert "craft_direction" in history
    assert "unexamined" in history
