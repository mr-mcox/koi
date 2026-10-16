"""Renders rubric.yaml sections into plain text for BAML prompt injection."""

import functools
from pathlib import Path
from typing import Any

import yaml

_RUBRIC_PATH = Path(__file__).resolve().parents[3] / "rubric.yaml"


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return yaml.safe_load(_RUBRIC_PATH.read_text(encoding="utf-8"))


def _render_one_dimension(dim: dict[str, Any]) -> list[str]:
    lines: list[str] = [f"\n### {dim['label']} (slug: {dim['slug']}, weight: {dim['weight']})"]
    lines.append(dim["definition"].strip())
    lines.append("Fit anchors:")
    for label, text in dim.get("fit_anchors", {}).items():
        lines.append(f"  {label}: {str(text).strip()}")
    if dim.get("look_for"):
        lines.append(f"Look for: {dim['look_for'].strip()}")
    return lines


def _render_dimensions(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["\n## Scored dimensions"]
    for dim in data.get("dimensions", []):
        lines.extend(_render_one_dimension(dim))
    return lines


def _render_non_scoring(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["\n## Non-scoring targets"]
    for ns in data.get("non_scoring", []):
        lines.append(f"- {ns['slug']}: {ns['definition'].strip()}")
    return lines


def rubric_text_for_baml() -> str:
    """Render all rubric sections into a flat text block for BAML prompt injection.
    Dimensions and non-scoring targets are all included so the model has the
    closed vocabulary without needing to see the YAML structure.
    """
    data = _load()
    parts: list[list[str]] = [
        _render_dimensions(data),
        _render_non_scoring(data),
    ]
    return "\n".join(line for section in parts for line in section)


def all_dimension_slugs() -> list[str]:
    return [d["slug"] for d in _load().get("dimensions", [])]


def all_non_scoring_slugs() -> list[str]:
    return [n["slug"] for n in _load().get("non_scoring", [])]


def rubric_text_for_dimension(target: str) -> str:
    """One dimension's rubric text, verbatim — the fine-stage similarity gate (Jev) is
    scored against this dimension alone, never the full rubric, so it can't be swayed by
    unrelated dimensions' anchors. Falls back to the non-scoring entry's definition for
    `non_scoring:obtainability` and friends (no fit anchors — never scored, Wall 4).
    Raises `KeyError` for a slug in neither vocabulary."""
    data = _load()
    by_slug = {dim["slug"]: dim for dim in data.get("dimensions", [])}
    if target in by_slug:
        return "\n".join(_render_one_dimension(by_slug[target]))
    non_scoring_by_slug = {ns["slug"]: ns for ns in data.get("non_scoring", [])}
    ns = non_scoring_by_slug[target]
    return f"### {ns['label']} (slug: {ns['slug']}, non-scoring — never enters the rollup)\n{ns['definition'].strip()}"


def fit_anchors_for_dimension(target: str) -> dict[str, str]:
    """Return one dimension's fit anchor text keyed by the rubric's own labels. A
    non-scoring target (e.g. `non_scoring:obtainability`) has no fit anchors in
    `rubric.yaml` — its `fit` is recorded but never scored (Wall 4) — so this returns a
    placeholder set rather than raising."""
    data = _load()
    by_slug = {dim["slug"]: dim for dim in data.get("dimensions", [])}
    if target in by_slug:
        return {
            str(label): str(text).strip()
            for label, text in by_slug[target].get("fit_anchors", {}).items()
        }
    non_scoring_slugs = {ns["slug"] for ns in data.get("non_scoring", [])}
    if target in non_scoring_slugs:
        placeholder = (
            "Not applicable — this target is never scored (Wall 4); fit is recorded but unused."
        )
        return {"Poor": placeholder, "Mixed": placeholder, "Strong": placeholder}
    raise KeyError(target)
