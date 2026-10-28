"""Tests for `screen.extract.prompt`: rubric.yaml text rendering for BAML/Jev prompts.

`RubricText.for_dimension`/`fit_anchors_for_dimension` must handle both scoring
dimensions and non-scoring targets (e.g. `non_scoring:obtainability`) without
crashing — a `KeyError` here took down the live Jev classifier and the backfill
command on any obtainability assertion.
"""

from __future__ import annotations

import pytest

from screen.extract.prompt import (
    MissingPrivateConfigError,
    RubricText,
    all_dimension_slugs,
    all_non_scoring_slugs,
    fit_anchors_for_dimension,
    unresolved_rubric_text_for_dimension,
)
from tests.helpers import synthetic_rubric


def test_rubric_text_for_baml_includes_dimensions_and_non_scoring() -> None:
    text = synthetic_rubric().full()
    assert "craft_direction" in text
    assert "non_scoring:obtainability" in text


def test_all_dimension_slugs_includes_craft_direction() -> None:
    assert "craft_direction" in all_dimension_slugs()


def test_all_non_scoring_slugs_includes_obtainability() -> None:
    assert "non_scoring:obtainability" in all_non_scoring_slugs()


def test_rubric_text_for_dimension_renders_a_scoring_dimension() -> None:
    text = synthetic_rubric().for_dimension("craft_direction")
    assert "craft_direction" in text
    assert "Fit anchors:" in text


def test_rubric_text_for_dimension_handles_non_scoring_target_without_crashing() -> None:
    """The bug this guards: non-scoring targets used to KeyError every live Jev call."""
    text = synthetic_rubric().for_dimension("non_scoring:obtainability")
    assert "Obtainability" in text
    assert "non-scoring" in text


def test_rubric_text_for_dimension_raises_for_unknown_slug() -> None:
    with pytest.raises(KeyError):
        synthetic_rubric().for_dimension("not_a_real_slug")


def test_fit_anchors_for_dimension_returns_rubric_anchors_for_scoring_dimension() -> None:
    anchors = fit_anchors_for_dimension("craft_direction")
    assert set(anchors) == {"Poor", "Mixed", "Strong"}


def test_fit_anchors_for_dimension_returns_placeholder_for_non_scoring_target() -> None:
    """Fit is recorded but never scored (Wall 4) for non-scoring targets — Jev still
    needs *some* anchors to avoid crashing, even though the value is unused downstream."""
    anchors = fit_anchors_for_dimension("non_scoring:obtainability")
    assert set(anchors) == {"Poor", "Mixed", "Strong"}
    assert all("never scored" in text for text in anchors.values())


def test_fit_anchors_for_dimension_raises_for_unknown_slug() -> None:
    with pytest.raises(KeyError):
        fit_anchors_for_dimension("not_a_real_slug")


def test_compensation_rubric_resolves_the_private_baseline() -> None:
    """The regression: Jev was asked "is comp above SCREEN_COMPENSATION_BASELINE?" and
    never given the number, so it judged against a variable name. The baseline is private
    (never in rubric.yaml) but must reach the prompt at render time."""
    text = RubricText.load({"SCREEN_COMPENSATION_BASELINE": "$999,999"}).for_dimension(
        "compensation"
    )

    assert "$999,999" in text
    assert "SCREEN_COMPENSATION_BASELINE" not in text


def test_unresolved_compensation_rubric_keeps_the_placeholder() -> None:
    """The regression: recalibration shows this text to a proposer that rewrites it and
    writes it back to the public rubric.yaml, so it must never carry the private value."""
    text = unresolved_rubric_text_for_dimension("compensation")

    assert "SCREEN_COMPENSATION_BASELINE" in text


def test_unset_baseline_raises_instead_of_rendering_a_placeholder() -> None:
    """The regression this guards: any stand-in for the baseline (a variable name, an
    "unset" marker) lets the pipeline run and produce confident compensation judgments
    made against nothing. Unset must stop the render."""
    with pytest.raises(MissingPrivateConfigError, match="SCREEN_COMPENSATION_BASELINE"):
        RubricText.load({})


def test_blank_baseline_is_treated_as_unset() -> None:
    """`.env.example` ships the key with an empty value, so a copied-but-unfilled .env
    must fail the same way a missing key does."""
    with pytest.raises(MissingPrivateConfigError):
        RubricText.load({"SCREEN_COMPENSATION_BASELINE": ""})


def test_full_rubric_render_also_resolves_the_baseline() -> None:
    """The full render feeds research and extraction; it must resolve the baseline too,
    or those stages inherit the same silent failure."""
    text = RubricText.load({"SCREEN_COMPENSATION_BASELINE": "$999,999"}).full()

    assert "$999,999" in text
    assert "SCREEN_COMPENSATION_BASELINE" not in text
