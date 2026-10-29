"""Unit tests for `screen.score.loader` — the one place the Scorer's config touches the
filesystem (`screen.score.scorer` itself is I/O-free)."""

from dataclasses import replace

import pytest

from screen.score.loader import load_scoring_config


def test_loads_real_rubric_and_scoring_yaml() -> None:
    config = load_scoring_config()
    assert config.total_weight == sum(config.dimension_weights.values())
    assert set(config.dimension_guards) == set(config.dimension_weights)
    assert config.provenance_weight["unexamined"] == 0.0
    assert config.provenance_weight["ratified"] > config.provenance_weight["model_proposed"]
    assert config.top_k > 0
    assert config.guard_downside > 0.0
    assert 0.0 < config.guard_upside < config.guard_downside
    assert 0.0 <= config.boundary_weight_floor < 1.0
    assert 0.0 < config.jev_confidence_threshold <= 1.0
    assert config.jev_few_shot_examples > 0


@pytest.mark.parametrize("floor", [0.0, 1.0])
def test_boundary_weight_floor_must_be_strictly_between_zero_and_one(floor: float) -> None:
    """At 0 an opening that looks settled out of top K gets no research or comparison
    attention at all; at 1 the boundary signal is erased."""
    with pytest.raises(ValueError, match="boundary_weight_floor"):
        replace(load_scoring_config(), boundary_weight_floor=floor)
