"""Unit tests for `screen.score.loader` — the one place the Scorer's config touches the
filesystem (`screen.score.scorer` itself is I/O-free)."""

import pytest

from screen.score.loader import _parse_tolerability, load_scoring_config


def test_loads_real_rubric_and_scoring_yaml() -> None:
    config = load_scoring_config()
    assert config.bar == 0.60
    assert config.total_weight == sum(config.dimension_weights.values())
    assert set(config.constraints) == {"location", "internal_culture", "extractive_business"}
    assert config.provenance_weight["unexamined"] == 0.0
    assert config.provenance_weight["ratified"] > config.provenance_weight["model_proposed"]


def test_parse_tolerability_single_value() -> None:
    assert _parse_tolerability("1.0") == (1.0, 1.0)


def test_parse_tolerability_range() -> None:
    assert _parse_tolerability("0.15 – 0.95") == (0.15, 0.95)


def test_parse_tolerability_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="unparseable tolerability value"):
        _parse_tolerability("not a number")
