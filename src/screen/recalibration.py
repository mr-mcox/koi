"""Core logic for the rubric recalibration loop.

This module is the testable core: data loading, split, objective scoring, and
round sequencing. The paid Anthropic proposer and CLI plumbing live in
`scripts/recalibrate_rubric.py` so this file stays small enough for the coverage gate.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from screen.store.repo import comparisons_for_target, get_dimension_digest

# ---------------------------------------------------------------------------
# Privacy gate — mirrors tests/test_rubric.py::PRIVATE_PATTERNS
# ---------------------------------------------------------------------------

_PRIVATE_PATTERNS: tuple[str, ...] = ("$230", "230,000", "230K")


class PrivacyViolationError(ValueError):
    """Candidate rubric text contains a private value."""


def validate_candidate(text: str) -> None:
    """Raise PrivacyViolationError if text contains any private pattern."""
    for pattern in _PRIVATE_PATTERNS:
        if pattern in text:
            raise PrivacyViolationError(
                f"Candidate rubric text contains private pattern {pattern!r}. "
                "The proposer hallucinated a private value; discarding candidate."
            )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UsablePair:
    pair_id: str
    opening_a_id: str
    opening_b_id: str
    digest_a: str
    digest_b: str
    expected: str  # "a" | "b" | "tie"


@dataclass(frozen=True)
class LabeledCase:
    """A labeled pair shown to the proposer — digest text, not opening IDs."""

    digest_a: str
    digest_b: str
    expected: str
    jev_prediction: str
    jev_confidence: float


@dataclass
class BucketCounts:
    right_sure: int = 0
    right_unsure: int = 0
    wrong_sure: int = 0
    wrong_unsure: int = 0

    @property
    def total(self) -> int:
        return self.right_sure + self.right_unsure + self.wrong_sure + self.wrong_unsure

    @property
    def precision_when_sure(self) -> float:
        denom = self.right_sure + self.wrong_sure
        return self.right_sure / denom if denom else 0.0

    def __str__(self) -> str:
        return (
            f"right+sure {self.right_sure}  right+unsure {self.right_unsure}  "
            f"wrong+sure {self.wrong_sure}  wrong+unsure {self.wrong_unsure}  "
            f"(precision-when-sure {self.precision_when_sure:.0%})"
        )


@dataclass
class RoundResult:
    round_num: int
    candidate_rubric_text: str
    held_out_buckets: BucketCounts
    theory: str
    train_buckets: BucketCounts | None = None


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class Proposer(Protocol):
    def propose(
        self,
        *,
        current_rubric_text: str,
        labeled_cases: list[LabeledCase],
        prior_rounds: list[RoundResult],
    ) -> str: ...


class Evaluator(Protocol):
    def evaluate(self, pairs: list[UsablePair], rubric_text: str) -> BucketCounts: ...


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------


def objective(counts: BucketCounts, rubric_text: str) -> tuple[int, int, int, int]:
    """Lexicographic objective: more right, more right-sure, fewer wrong-sure, shorter."""
    right_total = counts.right_sure + counts.right_unsure
    right_sure = counts.right_sure
    wrong_sure = -counts.wrong_sure
    brevity = -len(rubric_text.strip())
    return (right_total, right_sure, wrong_sure, brevity)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_pairs(
    conn: sqlite3.Connection,
    target: str,
    floor: int = 70,
) -> tuple[list[UsablePair], int]:
    """Load usable operator-only pairs for a target.

    Returns (pairs, shortfall). A nonzero shortfall means ineligible.
    """
    comparisons = [c for c in comparisons_for_target(conn, target) if c.provenance == "operator"]
    pairs: list[UsablePair] = []
    for c in comparisons:
        da = get_dimension_digest(conn, c.opening_a_id, target)
        db = get_dimension_digest(conn, c.opening_b_id, target)
        if da is None or db is None:
            continue
        pairs.append(
            UsablePair(
                pair_id=c.id,
                opening_a_id=c.opening_a_id,
                opening_b_id=c.opening_b_id,
                digest_a=da.digest,
                digest_b=db.digest,
                expected=c.outcome,
            )
        )
    shortfall = max(0, floor - len(pairs))
    return ([] if shortfall else pairs, shortfall)


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------


def split_pairs(
    pairs: list[UsablePair],
    seed: int = 42,
    held_fraction: float = 0.20,
) -> tuple[list[UsablePair], list[UsablePair]]:
    """Deterministic propose / held-out split."""
    rng = random.Random(seed)
    shuffled = list(pairs)
    rng.shuffle(shuffled)
    n_held = max(1, round(len(shuffled) * held_fraction))
    return shuffled[n_held:], shuffled[:n_held]


# ---------------------------------------------------------------------------
# Round loop
# ---------------------------------------------------------------------------


def run_rounds(
    *,
    propose_pairs: list[UsablePair],
    held_pairs: list[UsablePair],
    labeled_cases: list[LabeledCase],
    current_rubric_text: str,
    proposer: Proposer,
    evaluator: Evaluator,
    n_rounds: int = 3,
    baseline_train: BucketCounts | None = None,
) -> list[RoundResult]:
    """Run sequential rounds.
    not used to choose the winning candidate.
    """
    rounds: list[RoundResult] = []
    rubric_text = current_rubric_text
    if baseline_train is None:
        baseline_train = evaluator.evaluate(propose_pairs, rubric_text)
    best_train_score = objective(baseline_train, rubric_text)
    for i in range(n_rounds):
        candidate = proposer.propose(
            current_rubric_text=rubric_text,
            labeled_cases=labeled_cases,
            prior_rounds=list(rounds),
        )
        validate_candidate(candidate)
        train_buckets = evaluator.evaluate(propose_pairs, candidate)
        held_buckets = evaluator.evaluate(held_pairs, candidate)
        theory_line = next(
            (
                ln.lstrip("# ").strip()
                for ln in candidate.splitlines()
                if ln.startswith("# theory:")
            ),
            "(no theory stated)",
        )
        rounds.append(
            RoundResult(
                round_num=i + 1,
                candidate_rubric_text=candidate,
                held_out_buckets=held_buckets,
                theory=theory_line,
                train_buckets=train_buckets,
            )
        )
        candidate_score = objective(train_buckets, candidate)
        if candidate_score > best_train_score:
            rubric_text = candidate
            best_train_score = candidate_score

    return rounds


def best_round(
    rounds: list[RoundResult], baseline: BucketCounts, baseline_text: str
) -> RoundResult | None:
    """Return the best round on the propose split, or None."""
    baseline_score = objective(baseline, baseline_text)
    scored_rounds = [
        r
        for r in rounds
        if objective(r.train_buckets or r.held_out_buckets, r.candidate_rubric_text)
        > baseline_score
    ]
    if not scored_rounds:
        return None
    return max(
        scored_rounds,
        key=lambda r: objective(r.train_buckets or r.held_out_buckets, r.candidate_rubric_text),
    )
