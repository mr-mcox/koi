"""Loads `rubric.yaml` and `scoring.yaml` into a `ScoringConfig`. The only place in
`screen.score` that touches the filesystem — `scorer.py` stays pure (no I/O).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from screen.score.types import ConstraintRange, ScoringConfig
from screen.types import Provenance

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUBRIC_PATH = _REPO_ROOT / "rubric.yaml"
_SCORING_PATH = _REPO_ROOT / "scoring.yaml"

_TOLERABILITY_RE = re.compile(r"^\s*([0-9.]+)(?:\s*[–-]\s*([0-9.]+))?\s*$")

_NOT_EXAMINED_LABEL = "Not examined"


def _parse_tolerability(raw: str) -> tuple[float, float]:
    """`rubric.yaml` situations carry a tolerability as either a single value ("1.0") or a
    range ("0.15 – 0.95"). Both parse to a `(lo, hi)` pair; a single value is `(v, v)`."""
    match = _TOLERABILITY_RE.match(raw)
    if not match:
        raise ValueError(f"unparseable tolerability value: {raw!r}")
    lo = float(match.group(1))
    hi = float(match.group(2)) if match.group(2) is not None else lo
    return lo, hi


def _constraint_range(constraint: dict[str, Any]) -> ConstraintRange:
    examined = [s for s in constraint["situations"] if s["label"] != _NOT_EXAMINED_LABEL]
    unexamined = next(s for s in constraint["situations"] if s["label"] == _NOT_EXAMINED_LABEL)
    bounds = [_parse_tolerability(s["tolerability"]) for s in examined]
    worst = min(lo for lo, _ in bounds)
    best = max(hi for _, hi in bounds)
    unexamined_lo, unexamined_hi = _parse_tolerability(unexamined["tolerability"])
    return ConstraintRange(
        worst=worst, best=best, unexamined_lo=unexamined_lo, unexamined_hi=unexamined_hi
    )


def load_scoring_config(
    rubric_path: Path = _RUBRIC_PATH, scoring_path: Path = _SCORING_PATH
) -> ScoringConfig:
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    scoring = yaml.safe_load(scoring_path.read_text(encoding="utf-8"))

    dimension_weights = {d["slug"]: int(d["weight"]) for d in rubric["dimensions"]}
    constraints = {c["slug"]: _constraint_range(c) for c in rubric["constraints"]}
    provenance_weight: dict[Provenance, float] = {
        provenance: float(weight) for provenance, weight in scoring["provenance_weight"].items()
    }

    return ScoringConfig(
        bar=float(scoring["bar"]),
        seed=int(scoring["seed"]),
        samples=int(scoring["samples"]),
        provenance_weight=provenance_weight,
        dimension_weights=dimension_weights,
        constraints=constraints,
        dimension_ruling_hw_max=float(scoring["dimension_ruling"]["hw_max"]),
        dimension_ruling_hw_min=float(scoring["dimension_ruling"]["hw_min"]),
        rating_task_budget=int(scoring["rating_task_budget"]),
        top_k=int(scoring["top_k"]),
        research_turns_budget=int(scoring["research_turns_budget"]),
    )
