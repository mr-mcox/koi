"""rubric.yaml structural tests.
Verifies that the committed rubric has a well-formed shape, does not
contain private data, and stays in sync with the closed Target vocabulary
in screen.types. Dimension membership is not pinned here —
test_rubric_slugs_match_target_literal is the sync check; adding a rubric
slug only requires updating screen.types alongside rubric.yaml.
"""

import typing
from pathlib import Path

import pytest
import yaml

from screen.extract.prompt import RubricText, all_dimension_slugs
from screen.types import Target
from tests.helpers import synthetic_rubric

RUBRIC_PATH = Path(__file__).resolve().parents[1] / "rubric.yaml"


@pytest.fixture(scope="module")
def rubric() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))


def test_rubric_file_exists() -> None:
    assert RUBRIC_PATH.exists(), f"rubric.yaml not found at {RUBRIC_PATH}"


def test_rubric_has_no_version_field(rubric: dict) -> None:  # type: ignore[type-arg]
    """Dropped deliberately: git history is the change log, and there is no scenario yet
    where multiple rubric versions are live at once."""
    assert "version" not in rubric
    assert "revision_note" not in rubric


def test_rubric_dimension_slugs_are_unique(rubric: dict) -> None:  # type: ignore[type-arg]
    slugs = [d["slug"] for d in rubric.get("dimensions", [])]
    assert len(slugs) == len(set(slugs)), f"duplicate dimension slugs: {slugs}"


def test_rubric_guard_field_is_boolean_where_present(rubric: dict) -> None:  # type: ignore[type-arg]
    for d in rubric.get("dimensions", []):
        if "guard" in d:
            assert isinstance(d["guard"], bool), f"{d['slug']} guard is not a bool"


def test_rubric_has_no_constraints_section(rubric: dict) -> None:  # type: ignore[type-arg]
    """Constraints retired as a target family (constraints-and-rubric.md): every scored
    target is an ordinary weighted dimension now."""
    assert "constraints" not in rubric


def test_rubric_has_no_non_scoring_section(rubric: dict) -> None:  # type: ignore[type-arg]
    """Non-scoring targets retired (cleanup item C): nothing read them, but the research
    planner spent turns and the extractor spent tokens on them."""
    assert "non_scoring" not in rubric


def test_rubric_file_still_references_the_baseline_by_name(rubric: dict) -> None:  # type: ignore[type-arg]
    """The committed rubric names the config key; `resolve_private` swaps in the real
    value at render time. If this reference is ever edited away, the substitution silently
    stops happening and Jev goes back to judging compensation against nothing."""
    comp = next(d for d in rubric["dimensions"] if d["slug"] == "compensation")

    assert "SCREEN_COMPENSATION_BASELINE" in str(comp.get("definition", ""))


def test_prompt_helper_slugs_match_rubric(rubric: dict) -> None:  # type: ignore[type-arg]
    """prompt.py helper functions must return the same slugs the YAML file declares."""
    assert set(all_dimension_slugs()) == {d["slug"] for d in rubric["dimensions"]}


def test_rubric_text_for_dimension_slices_one_dimension(rubric: dict) -> None:  # type: ignore[type-arg]
    """Jev's fine-stage gate needs one dimension's rubric text, not the whole rubric —
    load-bearing text is sliced verbatim (AGENTS.md), the same discipline as the full-rubric
    render, just narrower."""
    first = rubric["dimensions"][0]
    other = rubric["dimensions"][1]

    text = synthetic_rubric().for_dimension(first["slug"])

    assert first["definition"].strip() in text
    assert other["definition"].strip() not in text


def test_rubric_text_for_dimension_unknown_slug_raises(rubric: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(KeyError):
        synthetic_rubric().for_dimension("not-a-real-slug")


def test_rubric_slugs_match_target_literal(rubric: dict) -> None:  # type: ignore[type-arg]
    """Every slug in the rubric must appear in the closed Target Literal,
    and vice versa — the two must stay in sync. The Literal is hand-listed in
    screen.types rather than generated from the rubric, and this is the sole
    drift detector, so a new dimension slug must land in both places or this fails."""
    literal_values: set[str] = set(typing.get_args(Target))
    rubric_slugs: set[str] = {d["slug"] for d in rubric["dimensions"]}
    assert literal_values == rubric_slugs, (
        f"Target Literal and rubric slugs diverged.\n"
        f"In Literal but not rubric: {literal_values - rubric_slugs}\n"
        f"In rubric but not Literal: {rubric_slugs - literal_values}"
    )


def test_full_render_with_empty_sections_does_not_crash() -> None:
    """The full render must not raise when optional sections are empty."""
    result = RubricText({"dimensions": []}, private={}).full()
    assert "Scored dimensions" in result


def test_full_render_of_a_dimension_without_look_for() -> None:
    """A dimension without `look_for` renders without a "Look for" line."""
    result = RubricText(
        {
            "dimensions": [
                {
                    "slug": "domain",
                    "label": "Domain coolness",
                    "weight": 1,
                    "definition": "Test definition.",
                    "fit_anchors": {},
                    # no look_for key
                }
            ],
        },
        private={},
    ).full()
    assert "Domain coolness" in result
    assert "Look for" not in result
