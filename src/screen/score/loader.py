"""Loads `rubric.yaml` and `scoring.yaml` into a `ScoringConfig`. The only place in
`screen.score` that touches the filesystem — `scorer.py` stays pure (no I/O).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from screen.score.types import ComparisonBetaParams, ScoringConfig
from screen.types import Provenance

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUBRIC_PATH = _REPO_ROOT / "rubric.yaml"
_SCORING_PATH = _REPO_ROOT / "scoring.yaml"


def load_scoring_config(
    rubric_path: Path = _RUBRIC_PATH, scoring_path: Path = _SCORING_PATH
) -> ScoringConfig:
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    scoring = yaml.safe_load(scoring_path.read_text(encoding="utf-8"))

    dimension_weights = {d["slug"]: int(d["weight"]) for d in rubric["dimensions"]}
    dimension_guards = {d["slug"]: bool(d.get("guard", False)) for d in rubric["dimensions"]}
    provenance_weight: dict[Provenance, float] = {
        provenance: float(weight) for provenance, weight in scoring["provenance_weight"].items()
    }

    return ScoringConfig(
        seed=int(scoring["seed"]),
        samples=int(scoring["samples"]),
        provenance_weight=provenance_weight,
        dimension_weights=dimension_weights,
        dimension_guards=dimension_guards,
        guard_downside=float(scoring["guard_downside_multiplier"]),
        guard_upside=float(scoring["guard_upside_multiplier"]),
        top_k=int(scoring["top_k"]),
        boundary_weight_floor=float(scoring["boundary_weight_floor"]),
        research_target_action_cap=int(scoring["research_target_action_cap"]),
        comparison_beta=ComparisonBetaParams(
            operator=float(scoring["comparison_beta"]["operator"]),
            provisional=float(scoring["comparison_beta"]["provisional"]),
        ),
        jev_confidence_threshold=float(scoring["jev_confidence_threshold"]),
        jev_few_shot_examples=int(scoring["jev_few_shot_examples"]),
        comparison_jitter_sigma=float(scoring["comparison_jitter_sigma"]),
        tie_commit_threshold=float(scoring["tie_commit_threshold"]),
        winner_commit_threshold=float(scoring["winner_commit_threshold"]),
    )
