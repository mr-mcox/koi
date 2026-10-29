"""Tests for routing logic: given Jev's raw answers, decide auto-commit vs. operator review.

These tests are organized by the decision boundary:
- auto-commit cases show the exact verdicts we expect to commit
- operator cases show the exact verdicts we expect to surface with a hint
"""

import pytest

from screen.verdict.protocol import JevRuling, NoulJudgment
from screen.verdict.routing import route_verdict


def _ruling(clear_winner_p_true: float = 0.9, a_is_better_p_true: float = 0.9) -> JevRuling:
    return JevRuling(
        clear_winner=NoulJudgment(p_true=clear_winner_p_true),
        a_is_better=NoulJudgment(p_true=a_is_better_p_true),
    )


@pytest.mark.parametrize(
    ("ruling", "expected_outcome"),
    [
        pytest.param(_ruling(clear_winner_p_true=0.05), "tie", id="auto-commit-tie"),
        pytest.param(
            _ruling(clear_winner_p_true=0.95, a_is_better_p_true=0.92),
            "a",
            id="auto-commit-a",
        ),
        pytest.param(
            _ruling(clear_winner_p_true=0.95, a_is_better_p_true=0.08),
            "b",
            id="auto-commit-b",
        ),
        pytest.param(
            _ruling(clear_winner_p_true=0.10, a_is_better_p_true=0.75),
            "tie",
            id="auto-commit-tie-at-threshold",
        ),
    ],
)
def test_auto_commit_cases(ruling: JevRuling, expected_outcome: str) -> None:
    decision = route_verdict(ruling)

    assert decision.auto_commit is True
    assert decision.verdict.outcome == expected_outcome
    assert decision.hint is None


@pytest.mark.parametrize(
    ("ruling", "expected_outcome", "expected_hint_fragment"),
    [
        pytest.param(
            _ruling(clear_winner_p_true=0.20),
            "tie",
            "no clear winner",
            id="route-low-clear-winner-confidence",
        ),
        pytest.param(
            _ruling(clear_winner_p_true=0.20, a_is_better_p_true=0.95),
            "tie",
            "no clear winner",
            id="route-low-clear-winner-confidence-even-when-a-says-otherwise",
        ),
        pytest.param(
            _ruling(clear_winner_p_true=0.95, a_is_better_p_true=0.74),
            "a",
            "uncertain which",
            id="route-low-winner-confidence-a",
        ),
        pytest.param(
            _ruling(clear_winner_p_true=0.95, a_is_better_p_true=0.26),
            "b",
            "uncertain which",
            id="route-low-winner-confidence-b",
        ),
    ],
)
def test_operator_route_cases(
    ruling: JevRuling, expected_outcome: str, expected_hint_fragment: str
) -> None:
    decision = route_verdict(ruling)

    assert decision.auto_commit is False
    assert decision.verdict.outcome == expected_outcome
    assert decision.hint is not None
    assert expected_hint_fragment in decision.hint.lower()


def test_clear_winner_false_at_threshold_is_still_a_tie() -> None:
    ruling = _ruling(clear_winner_p_true=0.05, a_is_better_p_true=0.95)
    decision = route_verdict(ruling, tie_commit_threshold=0.90, winner_commit_threshold=0.75)

    assert decision.auto_commit is True
    assert decision.verdict.outcome == "tie"
    assert decision.hint is None


def test_a_commits_at_the_winner_threshold() -> None:
    ruling = _ruling(clear_winner_p_true=0.95, a_is_better_p_true=0.75)
    decision = route_verdict(ruling, tie_commit_threshold=0.90, winner_commit_threshold=0.75)

    assert decision.auto_commit is True
    assert decision.verdict.outcome == "a"
    assert decision.hint is None


def test_b_commits_at_the_winner_threshold() -> None:
    ruling = _ruling(clear_winner_p_true=0.95, a_is_better_p_true=0.25)
    decision = route_verdict(ruling, tie_commit_threshold=0.90, winner_commit_threshold=0.75)

    assert decision.auto_commit is True
    assert decision.verdict.outcome == "b"
    assert decision.hint is None
