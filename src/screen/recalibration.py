"""Core logic for the rubric recalibration loop.

This module is the testable core: data loading, split, scoring, round sequencing,
and the paired-acceptance rule. The paid proposer and CLI plumbing live in
`scripts/recalibrate_rubric.py` so this file stays small enough for the coverage gate.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
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
    """One pair shown to the proposer or stored in a run transcript."""

    pair_id: str
    digest_a: str
    digest_b: str
    expected: str
    jev_prediction: str
    jev_confidence: float
    sure: bool


@dataclass(frozen=True)
class RubricProposal:
    """Structured proposer output: reasoning separate from the rubric draft.

    Every rubric field is optional. A field left `None` means "I am not editing
    this", and `render_candidate_text` rehydrates it from the current draft —
    the proposer never has to retype text it did not intend to change, and a
    proposal that edits nothing renders byte-identically to its input.
    """

    theory: str
    expected_effect: str
    definition: str | None = None
    fit_anchor_poor: str | None = None
    fit_anchor_mixed: str | None = None
    fit_anchor_strong: str | None = None
    look_for: str | None = None


@dataclass(frozen=True)
class ConfusionMatrix:
    expected_a_pred_a: int = 0
    expected_a_pred_b: int = 0
    expected_a_pred_tie: int = 0
    expected_b_pred_a: int = 0
    expected_b_pred_b: int = 0
    expected_b_pred_tie: int = 0
    expected_tie_pred_a: int = 0
    expected_tie_pred_b: int = 0
    expected_tie_pred_tie: int = 0

    @classmethod
    def from_cases(cls, cases: list[LabeledCase]) -> ConfusionMatrix:
        counts = {
            "expected_a_pred_a": 0,
            "expected_a_pred_b": 0,
            "expected_a_pred_tie": 0,
            "expected_b_pred_a": 0,
            "expected_b_pred_b": 0,
            "expected_b_pred_tie": 0,
            "expected_tie_pred_a": 0,
            "expected_tie_pred_b": 0,
            "expected_tie_pred_tie": 0,
        }
        for case in cases:
            key = f"expected_{case.expected}_pred_{case.jev_prediction}"
            if key not in counts:
                raise ValueError(
                    f"unexpected expected/predicted pair: {case.expected!r}/{case.jev_prediction!r}"
                )
            counts[key] += 1
        return cls(**counts)

    def __str__(self) -> str:
        rows = [
            (
                "expected a",
                self.expected_a_pred_a,
                self.expected_a_pred_b,
                self.expected_a_pred_tie,
            ),
            (
                "expected b",
                self.expected_b_pred_a,
                self.expected_b_pred_b,
                self.expected_b_pred_tie,
            ),
            (
                "expected tie",
                self.expected_tie_pred_a,
                self.expected_tie_pred_b,
                self.expected_tie_pred_tie,
            ),
        ]
        return " | ".join(f"{label}: a={a} b={b} tie={tie}" for label, a, b, tie in rows)


@dataclass(frozen=True)
class EvaluationResult:
    buckets: BucketCounts
    cases: list[LabeledCase]
    confusion: ConfusionMatrix

    @classmethod
    def from_cases(cls, cases: list[LabeledCase]) -> EvaluationResult:
        buckets = BucketCounts.from_cases(cases)
        return cls(buckets=buckets, cases=cases, confusion=ConfusionMatrix.from_cases(cases))

    def diff_against(self, other: EvaluationResult) -> PairDelta:
        by_id = {case.pair_id: case for case in other.cases}
        fixed: list[LabeledCase] = []
        broken: list[LabeledCase] = []
        for case in self.cases:
            prev = by_id.get(case.pair_id)
            if prev is None:
                raise ValueError(f"missing pair {case.pair_id!r} in comparison baseline")
            now_right = case.jev_prediction == case.expected
            prev_right = prev.jev_prediction == prev.expected
            if now_right and not prev_right:
                fixed.append(case)
            elif prev_right and not now_right:
                broken.append(case)
        return PairDelta(fixed=fixed, broken=broken)


@dataclass(frozen=True)
class PairDelta:
    fixed: list[LabeledCase] = field(default_factory=list)
    broken: list[LabeledCase] = field(default_factory=list)

    @property
    def delta(self) -> int:
        return len(self.fixed) - len(self.broken)


@dataclass
class BucketCounts:
    right_sure: int = 0
    right_unsure: int = 0
    wrong_sure: int = 0
    wrong_unsure: int = 0

    @classmethod
    def from_cases(cls, cases: list[LabeledCase]) -> BucketCounts:
        counts = cls()
        for case in cases:
            right = case.jev_prediction == case.expected
            if right and case.sure:
                counts.right_sure += 1
            elif right:
                counts.right_unsure += 1
            elif case.sure:
                counts.wrong_sure += 1
            else:
                counts.wrong_unsure += 1
        return counts

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
    expected_effect: str = ""
    train_buckets: BucketCounts | None = None
    train_cases: list[LabeledCase] | None = None
    held_out_cases: list[LabeledCase] | None = None
    fixed_cases: list[LabeledCase] = field(default_factory=list)
    broken_cases: list[LabeledCase] = field(default_factory=list)
    noise_floor_delta: int = 0
    candidate_delta: int = 0
    accepted: bool = False


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
    ) -> RubricProposal: ...


class Evaluator(Protocol):
    def evaluate(self, pairs: list[UsablePair], rubric_text: str) -> EvaluationResult: ...


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
# Render helpers
# ---------------------------------------------------------------------------


def parse_rubric_fields(rubric_text: str) -> dict[str, str]:
    """Split rendered dimension text back into its editable fields.

    Mirrors `screen.extract.prompt._render_one_dimension`, which is the text Jev
    reads live; the two must stay in step or a rehydrated candidate silently
    differs in shape from the rubric it was derived from.
    """
    fields: dict[str, str] = {}
    lines = rubric_text.splitlines()
    try:
        anchors_at = lines.index("Fit anchors:")
    except ValueError:
        return fields
    look_for_at = next(
        (i for i, line in enumerate(lines) if line.startswith("Look for:")), len(lines)
    )
    heading_at = next(i for i, line in enumerate(lines) if line.startswith("### "))

    fields["definition"] = "\n".join(lines[heading_at + 1 : anchors_at]).strip()
    for line in lines[anchors_at + 1 : look_for_at]:
        label, _, text = line.strip().partition(":")
        key = f"fit_anchor_{label.strip().lower()}"
        fields[key] = text.strip()
    if look_for_at < len(lines):
        tail = " ".join(line.strip() for line in lines[look_for_at + 1 :])
        head = lines[look_for_at].split(":", 1)[1].strip()
        fields["look_for"] = f"{head} {tail}".strip()
    return fields


def render_candidate_text(current_rubric_text: str, proposal: RubricProposal) -> str:
    """Render a candidate using the live dimension shape.

    Fields the proposal left as `None` are rehydrated from `current_rubric_text`,
    so an unedited field round-trips verbatim and a proposal that edits nothing
    reproduces its input byte-for-byte. The theory and expected effect are never
    rendered — only rubric text reaches the evaluator.
    """
    lines = current_rubric_text.splitlines()
    heading_at = next((i for i, line in enumerate(lines) if line.startswith("### ")), None)
    if heading_at is None:
        raise ValueError("current rubric text is missing the dimension heading")

    current = parse_rubric_fields(current_rubric_text)

    def field(name: str) -> str:
        proposed = getattr(proposal, name)
        return current.get(name, "") if proposed is None else proposed.strip()

    rendered = lines[: heading_at + 1] + [field("definition"), "Fit anchors:"]
    for label in ("Poor", "Mixed", "Strong"):
        rendered.append(f"  {label}: {field(f'fit_anchor_{label.lower()}')}")
    look_for = field("look_for")
    if look_for:
        rendered.append(f"Look for: {look_for}")
    return "\n".join(rendered)


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
    baseline_train: EvaluationResult | None = None,
    baseline_noise: EvaluationResult | None = None,
    noise_floor_delta: int | None = None,
    round_offset: int = 0,
    on_round: Callable[[RoundResult], None] | None = None,
) -> list[RoundResult]:
    """Run sequential rounds.

    The proposer always sees the current-best train cases. Acceptance is paired:
    a candidate must beat the baseline noise delta (from evaluating the current
    best twice) before the aggregate objective can break ties.
    """
    rounds: list[RoundResult] = []
    rubric_text = current_rubric_text
    current_train = baseline_train or evaluator.evaluate(propose_pairs, rubric_text)
    current_noise = baseline_noise or evaluator.evaluate(propose_pairs, rubric_text)
    if noise_floor_delta is None:
        noise_floor_delta = current_noise.diff_against(current_train).delta
    current_score = objective(current_train.buckets, rubric_text)
    current_cases = list(current_train.cases)

    for i in range(n_rounds):
        proposal = proposer.propose(
            current_rubric_text=rubric_text,
            labeled_cases=current_cases,
            prior_rounds=list(rounds),
        )
        candidate = render_candidate_text(rubric_text, proposal)
        validate_candidate(candidate)
        candidate_train = evaluator.evaluate(propose_pairs, candidate)
        candidate_held = evaluator.evaluate(held_pairs, candidate)
        delta = candidate_train.diff_against(current_train)
        candidate_score = objective(candidate_train.buckets, candidate)
        accepted = False
        if delta.delta > noise_floor_delta:
            accepted = True
        elif delta.delta == noise_floor_delta and candidate_score > current_score:
            accepted = True
        if accepted:
            rubric_text = candidate
            current_train = candidate_train
            current_score = candidate_score
            current_cases = list(candidate_train.cases)

        rounds.append(
            RoundResult(
                round_num=round_offset + i + 1,
                candidate_rubric_text=candidate,
                held_out_buckets=candidate_held.buckets,
                theory=proposal.theory,
                expected_effect=proposal.expected_effect,
                train_buckets=candidate_train.buckets,
                train_cases=candidate_train.cases,
                held_out_cases=candidate_held.cases,
                fixed_cases=delta.fixed,
                broken_cases=delta.broken,
                noise_floor_delta=noise_floor_delta,
                candidate_delta=delta.delta,
                accepted=accepted,
            )
        )

        if on_round is not None:
            on_round(rounds[-1])

    return rounds


def best_round(
    rounds: list[RoundResult], baseline: BucketCounts, baseline_text: str
) -> RoundResult | None:
    """Return the final accepted round, or fall back to the old objective-based pick."""
    accepted = [r for r in rounds if r.accepted]
    if accepted:
        return accepted[-1]
    baseline_score = objective(baseline, baseline_text)
    scored_rounds = [
        r
        for r in rounds
        if r.train_buckets is not None
        and objective(r.train_buckets, r.candidate_rubric_text) > baseline_score
    ]
    if not scored_rounds:
        return None
    return max(
        scored_rounds, key=lambda r: objective(r.train_buckets or baseline, r.candidate_rubric_text)
    )
