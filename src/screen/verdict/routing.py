"""Pure routing logic: given Jev's raw answers (clear_winner + a_is_better), decide
whether to auto-commit or surface to the operator for review.

This separates Jev's I/O (calling the API, parsing answers) from decision logic, making
the latter testable and understandable independent of the TypeSafe SDK.
"""

from __future__ import annotations

from dataclasses import dataclass

from screen.verdict.protocol import JevRuling, RubricVerdict, VerdictOutcome

_TRUE_THRESHOLD = 0.5


@dataclass(frozen=True)
class RoutingDecision:
    """The outcome of applying routing logic to Jev's ruling. Either an auto-committed
    verdict, or a signal to surface it to the operator."""

    verdict: RubricVerdict
    auto_commit: bool
    hint: str | None = None


def _false_confidence(p_true: float) -> float:
    return 1.0 - p_true


def _winner_confidence(p_true: float) -> float:
    return max(p_true, 1.0 - p_true)


def route_verdict(
    ruling: JevRuling,
    tie_commit_threshold: float = 0.90,
    winner_commit_threshold: float = 0.75,
) -> RoutingDecision:
    """Interpret Jev's ruling and decide whether to auto-commit or route to operator.

    Routing logic:
    1. If Jev is confident the answer is false enough to clear the tie threshold,
       auto-commit a tie.
    2. If Jev is confident that there is a clear winner and confident enough on
       which side wins, auto-commit A or B.
    3. Otherwise, route to operator with the model's best guess preserved.
    """

    clear_false_confidence = _false_confidence(ruling.clear_winner.p_true)
    if clear_false_confidence >= tie_commit_threshold:
        return RoutingDecision(
            verdict=RubricVerdict(outcome="tie", confidence=clear_false_confidence),
            auto_commit=True,
        )

    clear_true_confidence = ruling.clear_winner.p_true
    winner_confidence = _winner_confidence(ruling.a_is_better.p_true)
    if (
        clear_true_confidence >= winner_commit_threshold
        and winner_confidence >= winner_commit_threshold
    ):
        outcome: VerdictOutcome = "a" if ruling.a_is_better.p_true >= _TRUE_THRESHOLD else "b"
        return RoutingDecision(
            verdict=RubricVerdict(outcome=outcome, confidence=winner_confidence),
            auto_commit=True,
        )

    if clear_true_confidence >= winner_commit_threshold:
        outcome = "a" if ruling.a_is_better.p_true >= _TRUE_THRESHOLD else "b"
        return RoutingDecision(
            verdict=RubricVerdict(outcome=outcome, confidence=winner_confidence),
            auto_commit=False,
            hint="Model detected a winner but uncertain which (low confidence)",
        )

    return RoutingDecision(
        verdict=RubricVerdict(outcome="tie", confidence=clear_false_confidence),
        auto_commit=False,
        hint="Model uncertain: no clear winner detected (low confidence)",
    )
