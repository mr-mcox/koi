"""Renders rubric.yaml sections into plain text for BAML prompt injection."""

import functools
from pathlib import Path
from typing import Any

import yaml

_RUBRIC_PATH = Path(__file__).resolve().parents[3] / "rubric.yaml"


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return yaml.safe_load(_RUBRIC_PATH.read_text(encoding="utf-8"))


def _render_confidence_tiers(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["## Confidence tiers"]
    for tier in data.get("confidence_tiers", []):
        counts = tier.get("counts_toward_score", True)
        lines.append(
            f"- {tier['tier']}: {tier['definition'].strip()} " f"(counts toward score: {counts})"
        )
    return lines


def _render_dimensions(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["\n## Scored dimensions"]
    for dim in data.get("dimensions", []):
        lines.append(f"\n### {dim['label']} (slug: {dim['slug']}, weight: {dim['weight']})")
        lines.append(dim["definition"].strip())
        lines.append("Fit anchors:")
        for label, text in dim.get("fit_anchors", {}).items():
            lines.append(f"  {label}: {str(text).strip()}")
        if dim.get("look_for"):
            lines.append(f"Look for: {dim['look_for'].strip()}")
    return lines


def _render_constraints(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["\n## Constraints (tolerability discounts)"]
    for con in data.get("constraints", []):
        lines.append(f"\n### {con['label']} (slug: {con['slug']})")
        lines.append(con["definition"].strip())
        lines.append("Situations:")
        for sit in con.get("situations", []):
            note = f" - {sit['notes'].strip()}" if sit.get("notes") else ""
            lines.append(f"  [{sit['tolerability']}] {sit['label']}{note}")
    return lines


def _render_non_scoring(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["\n## Non-scoring targets"]
    for ns in data.get("non_scoring", []):
        lines.append(f"- {ns['slug']}: {ns['definition'].strip()}")
    return lines


def rubric_text_for_baml() -> str:
    """Render all rubric sections into a flat text block for BAML prompt injection.

    Dimensions, constraints, and non-scoring targets are all included so the
    model has the closed vocabulary and fit anchors without needing to see
    the YAML structure.
    """
    data = _load()
    parts: list[list[str]] = [
        _render_confidence_tiers(data),
        _render_dimensions(data),
        _render_constraints(data),
        _render_non_scoring(data),
    ]
    return "\n".join(line for section in parts for line in section)


def all_dimension_slugs() -> list[str]:
    return [d["slug"] for d in _load().get("dimensions", [])]


def all_constraint_slugs() -> list[str]:
    return [c["slug"] for c in _load().get("constraints", [])]


def all_non_scoring_slugs() -> list[str]:
    return [n["slug"] for n in _load().get("non_scoring", [])]
