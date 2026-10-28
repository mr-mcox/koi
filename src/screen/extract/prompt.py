"""Renders rubric.yaml sections into plain text for BAML prompt injection."""

import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

_RUBRIC_PATH = Path(__file__).resolve().parents[3] / "rubric.yaml"

# Private config referenced by name in `rubric.yaml` and substituted with the real value
# only at render time. The rubric file is public (AGENTS.md §Privacy, decisions.md R6), so
# the number lives in the environment; the model still needs it to answer the likelihood
# question the compensation anchors are written against.
PRIVATE_PLACEHOLDERS = ("SCREEN_COMPENSATION_BASELINE",)


class MissingPrivateConfigError(RuntimeError):
    """A rubric dimension references private config that the environment doesn't supply."""


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return yaml.safe_load(_RUBRIC_PATH.read_text(encoding="utf-8"))


def resolve_private(text: str, private: Mapping[str, str]) -> str:
    """Substitute private config names with their values from `private`.
    Raises when a referenced name is unset. Rendering the rubric without the baseline is
    never correct: the compensation anchors are all defined relative to it, so the model
    would score every opening against nothing and report confident-looking judgments.
    """
    for name in PRIVATE_PLACEHOLDERS:
        if name not in text:
            continue
        value = private.get(name)
        if not value:
            raise MissingPrivateConfigError(
                f"{name} is unset, but rubric.yaml references it. "
                f"Set it in .env (see .env.example) — it is private and never committed."
            )
        text = text.replace(name, value)
    return text


def _render_one_dimension(dim: dict[str, Any]) -> list[str]:
    lines: list[str] = [f"\n### {dim['label']} (slug: {dim['slug']}, weight: {dim['weight']})"]
    lines.append(dim["definition"].strip())
    lines.append("Fit anchors:")
    for label, text in dim.get("fit_anchors", {}).items():
        lines.append(f"  {label}: {str(text).strip()}")
    if dim.get("look_for"):
        lines.append(f"Look for: {dim['look_for'].strip()}")
    return lines


def _render_full(data: Mapping[str, Any]) -> str:
    lines: list[str] = ["\n## Scored dimensions"]
    for dim in data.get("dimensions", []):
        lines.extend(_render_one_dimension(dim))
    return "\n".join(lines)


def _render_dimension(data: Mapping[str, Any], target: str) -> str:
    by_slug = {dim["slug"]: dim for dim in data.get("dimensions", [])}
    if target not in by_slug:
        raise KeyError(target)
    return "\n".join(_render_one_dimension(by_slug[target]))


class RubricText:
    """The rubric rendered for model prompts, private placeholders resolved.

    Built once at process start: a missing private value fails construction, so it
    surfaces at startup rather than partway through a research pass.
    """

    def __init__(self, data: Mapping[str, Any], private: Mapping[str, str]) -> None:
        self._data = data
        self._private = dict(private)
        self._full = resolve_private(_render_full(data), self._private)

    @classmethod
    def load(cls, environ: Mapping[str, str]) -> RubricText:
        """The committed `rubric.yaml`, with private values taken from `environ`."""
        return cls(_load(), {name: environ.get(name, "") for name in PRIVATE_PLACEHOLDERS})

    def full(self) -> str:
        """Every scored dimension, for research and extraction."""
        return self._full

    def for_dimension(self, target: str) -> str:
        """One dimension's text alone, so a per-dimension judgment can't be swayed by
        other dimensions' anchors. Raises `KeyError` for an unknown slug."""
        return resolve_private(_render_dimension(self._data, target), self._private)

    def resolve(self, text: str) -> str:
        """Resolve private placeholders in rubric text that originated elsewhere (e.g. a
        recalibration candidate)."""
        return resolve_private(text, self._private)


def all_dimension_slugs() -> list[str]:
    return [d["slug"] for d in _load().get("dimensions", [])]


def unresolved_rubric_text_for_dimension(target: str) -> str:
    """One dimension's text with private placeholders left as their names. For callers
    that show rubric text to a model that may rewrite it, or write it back to the public
    `rubric.yaml` — they must never hold the private value."""
    return _render_dimension(_load(), target)


def fit_anchors_for_dimension(target: str) -> dict[str, str]:
    """Return one dimension's fit anchor text keyed by the rubric's own labels.
    Raises `KeyError` for an unknown slug."""
    by_slug = {dim["slug"]: dim for dim in _load().get("dimensions", [])}
    if target not in by_slug:
        raise KeyError(target)
    return {
        str(label): str(text).strip()
        for label, text in by_slug[target].get("fit_anchors", {}).items()
    }
