"""rubric.yaml structural tests.
Verifies that the committed rubric has a well-formed shape, does not
contain private data, and stays in sync with the closed Target vocabulary
in screen.types. Dimension/constraint/non-scoring membership is not pinned
here — test_rubric_slugs_match_target_literal is the sync check; adding a
rubric slug only requires updating screen.types alongside rubric.yaml.
"""

import typing
from pathlib import Path

import pytest
import yaml

import screen.extract.prompt as prompt_module
from screen.extract.prompt import all_constraint_slugs, all_dimension_slugs, all_non_scoring_slugs
from screen.types import Target

RUBRIC_PATH = Path(__file__).resolve().parents[1] / "rubric.yaml"

# These names must not appear in any rubric text field (privacy boundary).
PRIVATE_PATTERNS = [
    "$230",
    "230,000",
    "230K",
]


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


def test_rubric_constraint_slugs_are_unique(rubric: dict) -> None:  # type: ignore[type-arg]
    slugs = [c["slug"] for c in rubric.get("constraints", [])]
    assert len(slugs) == len(set(slugs)), f"duplicate constraint slugs: {slugs}"


def test_rubric_non_scoring_slugs_carry_namespace_prefix(rubric: dict) -> None:  # type: ignore[type-arg]
    for entry in rubric.get("non_scoring", []):
        assert entry["slug"].startswith("non_scoring:"), entry["slug"]


def test_rubric_compensation_dimension_has_no_baseline_number(rubric: dict) -> None:  # type: ignore[type-arg]
    """The compensation baseline is private. The rubric definition must not
    contain the number — only a reference to the config key."""
    comp = next(d for d in rubric["dimensions"] if d["slug"] == "compensation")
    definition = str(comp.get("definition", ""))
    for pattern in PRIVATE_PATTERNS:
        assert pattern not in definition, (
            f"Compensation definition contains private baseline pattern '{pattern}'. "
            "Move it to SCREEN_COMPENSATION_BASELINE env var."
        )


def test_no_private_data_in_any_text_field(rubric: dict) -> None:  # type: ignore[type-arg]
    """Walk every string value in the rubric and assert no private patterns appear."""
    full_text = yaml.dump(rubric)
    for pattern in PRIVATE_PATTERNS:
        assert (
            pattern not in full_text
        ), f"Private pattern '{pattern}' found in rubric.yaml. Remove it."


def test_prompt_helper_slugs_match_rubric(rubric: dict) -> None:  # type: ignore[type-arg]
    """prompt.py helper functions must return the same slugs the YAML file declares."""
    assert set(all_dimension_slugs()) == {d["slug"] for d in rubric["dimensions"]}
    assert set(all_constraint_slugs()) == {c["slug"] for c in rubric["constraints"]}
    assert set(all_non_scoring_slugs()) == {n["slug"] for n in rubric["non_scoring"]}


def test_rubric_slugs_match_target_literal(rubric: dict) -> None:  # type: ignore[type-arg]
    """Every slug in the rubric must appear in the closed Target Literal,
    and vice versa — the two must stay in sync. This is the drift detector for
    Wall 3 (Target is hand-listed in screen.types, not generated from the
    rubric): it is the sole guard, so a new dimension/constraint/non-scoring
    slug must land in both places or this fails."""
    literal_values: set[str] = set(typing.get_args(Target))
    rubric_slugs: set[str] = (
        {d["slug"] for d in rubric["dimensions"]}
        | {c["slug"] for c in rubric["constraints"]}
        | {n["slug"] for n in rubric["non_scoring"]}
    )
    assert literal_values == rubric_slugs, (
        f"Target Literal and rubric slugs diverged.\n"
        f"In Literal but not rubric: {literal_values - rubric_slugs}\n"
        f"In rubric but not Literal: {rubric_slugs - literal_values}"
    )


def test_rubric_text_for_baml_empty_sections_do_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rubric_text_for_baml must not raise when optional sections are empty.
    Exercises the empty-list branch in each _render_* helper."""
    monkeypatch.setattr(
        prompt_module,
        "_load",
        lambda: {
            "dimensions": [],
            "constraints": [],
            "non_scoring": [],
        },
    )
    result = prompt_module.rubric_text_for_baml()
    assert "Scored dimensions" in result


def test_rubric_text_for_baml_dimension_without_look_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercises the `if dim.get('look_for')` False branch in _render_dimensions."""
    monkeypatch.setattr(
        prompt_module,
        "_load",
        lambda: {
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
            "constraints": [],
            "non_scoring": [],
        },
    )
    result = prompt_module.rubric_text_for_baml()
    assert "Domain coolness" in result
    assert "Look for" not in result
