"""Verify that the generated BAML StopAction type matches the hand-written domain type.

If field names diverge, baml_planner.py's coercion will silently get wrong
values. This test makes that a CI failure instead of a production surprise.

Mirrors the pattern in test_extract_baml_shape.py.
"""

from screen.baml_client.types import StopAction as BAMLStopAction
from screen.research.actions import StopAction

_STOP_ACTION_FIELDS = set(StopAction.model_fields.keys())


def test_baml_stop_action_fields_match_domain_type() -> None:
    """Generated BAML StopAction must have exactly the same field names
    as the hand-written screen.research.actions.StopAction. Any divergence
    means baml_planner.py's _coerce() is silently reading wrong fields."""
    baml_fields = set(BAMLStopAction.model_fields.keys())
    assert baml_fields == _STOP_ACTION_FIELDS, (
        f"BAML StopAction fields diverged from domain type.\n"
        f"In BAML only: {baml_fields - _STOP_ACTION_FIELDS}\n"
        f"In domain only: {_STOP_ACTION_FIELDS - baml_fields}\n"
        "Re-run `baml-cli generate` or update research.baml to match."
    )
