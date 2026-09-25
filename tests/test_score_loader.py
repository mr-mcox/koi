"""Unit tests for `screen.score.loader` — the one place the Scorer's config touches the
filesystem (`screen.score.scorer` itself is I/O-free)."""

from screen.score.loader import load_scoring_config


def test_loads_real_rubric_and_scoring_yaml() -> None:
    config = load_scoring_config()
    assert config.total_weight == sum(config.dimension_weights.values())
    assert {"location", "internal_culture"} <= set(config.dimension_weights)
    assert config.provenance_weight["unexamined"] == 0.0
    assert config.provenance_weight["ratified"] > config.provenance_weight["model_proposed"]
    assert config.top_k == 5
