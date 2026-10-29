"""Core logic for the rubric recalibration loop.

This module is the testable core: data loading, split, scoring, round sequencing,
and the paired-acceptance rule. The paid proposer and CLI plumbing live in
`scripts/recalibrate_rubric.py` so this file stays small enough for the coverage gate.
"""

from __future__ import annotations

import math
import random
import sqlite3
import statistics
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from screen.extract.prompt import PRIVATE_PLACEHOLDERS
from screen.store.repo import comparisons_for_target, get_dimension_digest
from screen.types import ComparisonOutcome


class PrivacyViolationError(ValueError):
    """Candidate rubric text contains a private value."""


def validate_candidate(text: str, private_values: Mapping[str, str]) -> None:
    """Raise PrivacyViolationError if text contains a configured private value. The
    proposer is shown these values, so a candidate can carry one back toward the public
    `rubric.yaml`."""
    for name in PRIVATE_PLACEHOLDERS:
        value = private_values.get(name)
        if value and value in text:
            raise PrivacyViolationError(
                f"Candidate rubric text contains the value of {name}; discarding candidate."
            )


class PlaceholderDroppedError(ValueError):
    """Candidate rubric text lost a private-config placeholder its source carried."""


def require_placeholders_kept(current_text: str, candidate_text: str) -> None:
    """Raise if the candidate drops a placeholder the current text uses.

    A dropped placeholder either leaves the dimension anchored to nothing or was replaced
    by a literal value, which would then be written into the public rubric.yaml.
    """
    for name in PRIVATE_PLACEHOLDERS:
        if name in current_text and name not in candidate_text:
            raise PlaceholderDroppedError(
                f"Candidate rubric text dropped the {name} placeholder; discarding candidate."
            )


@dataclass(frozen=True)
class UsablePair:
    pair_id: str
    opening_a_id: str
    opening_b_id: str
    digest_a: str
    digest_b: str
    expected: ComparisonOutcome


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
    p_clear: float
    p_a: float

    def outcome_probabilities(self) -> dict[str, float]:
        """Jev's distribution over the three rulings, from its two answers: P(clear
        winner) splits between a and b by P(a is better); the rest is tie."""
        return {
            "a": self.p_clear * self.p_a,
            "b": self.p_clear * (1 - self.p_a),
            "tie": 1 - self.p_clear,
        }

    @property
    def p_ruling(self) -> float:
        """Probability Jev put on the operator's ruling."""
        return self.outcome_probabilities()[self.expected]

    @property
    def brier(self) -> float:
        """Multiclass Brier score against the operator's ruling: 0 is certain and right,
        2 is certain and wrong. Proper, so it can't be gamed by blanket confidence."""
        return sum(
            (p - (1.0 if outcome == self.expected else 0.0)) ** 2
            for outcome, p in self.outcome_probabilities().items()
        )


@dataclass(frozen=True)
class CommitCosts:
    """What a wrong auto-commit costs, in operator looks saved by a right one.

    A pair Jev isn't sure of costs the operator one look whether Jev was right or not.
    Committing it saves that look if right and costs k if wrong, so committing breaks
    even at precision k/(k+1). Reading each commit threshold t as that break-even point
    gives k = t/(1-t).
    """

    k_winner: float
    k_tie: float

    @classmethod
    def from_thresholds(
        cls, *, winner_commit_threshold: float, tie_commit_threshold: float
    ) -> CommitCosts:
        def k(t: float) -> float:
            return t / (1 - t)

        return cls(k_winner=k(winner_commit_threshold), k_tie=k(tie_commit_threshold))

    def net(self, cases: list[LabeledCase]) -> float:
        """Looks saved net of silent errors: each right+sure is +1, each wrong+sure
        costs k for the threshold it crossed. Unsure cases cost a look either way."""
        total = 0.0
        for case in cases:
            if not case.sure:
                continue
            if case.jev_prediction == case.expected:
                total += 1
            else:
                total -= self.k_tie if case.jev_prediction == "tie" else self.k_winner
        return total


@dataclass(frozen=True)
class Score:
    net: float
    brier: float

    @classmethod
    def of(cls, cases: list[LabeledCase], costs: CommitCosts) -> Score:
        return cls(net=costs.net(cases), brier=mean_brier(cases))


def mean_brier(cases: list[LabeledCase]) -> float:
    return statistics.fmean(case.brier for case in cases) if cases else 0.0


_BRIER_GAIN_PER_CHAR_SAVED = 1e-4
"""Exchange rate between rubric brevity and Brier gain when net is tied."""

# Two standard errors: a gain this size from jitter alone happens ~5% of the time.
_NOISE_FLOOR_STANDARD_ERRORS = 2
_MIN_SAMPLES_FOR_STDEV = 2


def brier_noise_floor(first: EvaluationResult, second: EvaluationResult) -> float:
    """Two standard errors of the mean Brier difference between two evaluations of the
    same text. Jev's verdicts barely move between runs but its probabilities jitter, so
    a mean-Brier gain smaller than this is indistinguishable from re-running Jev."""
    by_id = {case.pair_id: case for case in second.cases}
    diffs = [case.brier - by_id[case.pair_id].brier for case in first.cases]
    if len(diffs) < _MIN_SAMPLES_FOR_STDEV:
        return 0.0
    return _NOISE_FLOOR_STANDARD_ERRORS * statistics.stdev(diffs) / math.sqrt(len(diffs))


def accepts(
    candidate: Score,
    current: Score,
    *,
    brier_floor: float,
    candidate_text: str,
    current_text: str,
) -> bool:
    """Lexicographic: higher net, then a combined Brier and length gain beyond the noise floor.
    A Brier difference inside the floor counts as a tie unless offset by length."""
    if not math.isclose(candidate.net, current.net, abs_tol=1e-9):
        return candidate.net > current.net

    brier_gain = current.brier - candidate.brier
    length_gain = len(current_text.strip()) - len(candidate_text.strip())

    adjusted_brier_gain = brier_gain + length_gain * _BRIER_GAIN_PER_CHAR_SAVED

    if abs(adjusted_brier_gain) > brier_floor:
        return adjusted_brier_gain > 0
    return len(candidate_text.strip()) < len(current_text.strip())


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
    train_net: float = 0.0
    train_brier: float = 0.0
    accepted: bool = False


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


def _noop_round_start(round_num: int) -> None:
    return None


def _noop_stage_done(round_num: int, stage: str, elapsed: float) -> None:
    return None


def _noop_round(round_result: RoundResult) -> None:
    return None


def _run_round_iteration(
    *,
    round_num: int,
    rubric_text: str,
    current_train: EvaluationResult,
    propose_pairs: list[UsablePair],
    held_pairs: list[UsablePair],
    proposer: Proposer,
    evaluator: Evaluator,
    costs: CommitCosts,
    brier_floor: float,
    prior_rounds: list[RoundResult],
    private_values: Mapping[str, str],
    on_stage_done: Callable[[int, str, float], None] = _noop_stage_done,
) -> tuple[RoundResult, str, EvaluationResult, Score]:
    """Run one propose/evaluate step and return the new state plus the record."""

    stage_started = time.monotonic()
    proposal = proposer.propose(
        current_rubric_text=rubric_text,
        labeled_cases=list(current_train.cases),
        prior_rounds=prior_rounds,
    )
    on_stage_done(round_num, "proposal", time.monotonic() - stage_started)

    candidate = render_candidate_text(rubric_text, proposal)
    validate_candidate(candidate, private_values)
    require_placeholders_kept(rubric_text, candidate)

    stage_started = time.monotonic()
    candidate_train = evaluator.evaluate(propose_pairs, candidate)
    on_stage_done(round_num, "train-eval", time.monotonic() - stage_started)

    stage_started = time.monotonic()
    candidate_held = evaluator.evaluate(held_pairs, candidate)
    on_stage_done(round_num, "held-eval", time.monotonic() - stage_started)

    delta = candidate_train.diff_against(current_train)
    candidate_score = Score.of(candidate_train.cases, costs)
    accepted = accepts(
        candidate_score,
        Score.of(current_train.cases, costs),
        brier_floor=brier_floor,
        candidate_text=candidate,
        current_text=rubric_text,
    )
    if accepted:
        rubric_text = candidate
        current_train = candidate_train

    return (
        RoundResult(
            round_num=round_num,
            candidate_rubric_text=candidate,
            held_out_buckets=candidate_held.buckets,
            theory=proposal.theory,
            expected_effect=proposal.expected_effect,
            train_buckets=candidate_train.buckets,
            train_cases=candidate_train.cases,
            held_out_cases=candidate_held.cases,
            fixed_cases=delta.fixed,
            broken_cases=delta.broken,
            train_net=candidate_score.net,
            train_brier=candidate_score.brier,
            accepted=accepted,
        ),
        rubric_text,
        current_train,
        candidate_score,
    )


def run_rounds(
    *,
    propose_pairs: list[UsablePair],
    held_pairs: list[UsablePair],
    current_rubric_text: str,
    proposer: Proposer,
    evaluator: Evaluator,
    costs: CommitCosts,
    brier_floor: float,
    private_values: Mapping[str, str],
    n_rounds: int = 3,
    baseline_train: EvaluationResult | None = None,
    round_offset: int = 0,
    on_round: Callable[[RoundResult], None] = _noop_round,
    on_round_start: Callable[[int], None] = _noop_round_start,
    on_stage_done: Callable[[int, str, float], None] = _noop_stage_done,
) -> list[RoundResult]:
    """Run sequential rounds; the proposer always sees the current-best train cases.

    Acceptance is `accepts` on the train split. Held-out is measured and recorded but
    never consulted, so it stays an honest estimate of the accepted text.
    """
    rounds: list[RoundResult] = []
    rubric_text = current_rubric_text
    current_train = baseline_train or evaluator.evaluate(propose_pairs, rubric_text)

    for i in range(n_rounds):
        round_num = round_offset + i + 1
        on_round_start(round_num)
        round_result, rubric_text, current_train, _ = _run_round_iteration(
            round_num=round_num,
            rubric_text=rubric_text,
            current_train=current_train,
            propose_pairs=propose_pairs,
            held_pairs=held_pairs,
            proposer=proposer,
            evaluator=evaluator,
            costs=costs,
            brier_floor=brier_floor,
            prior_rounds=list(rounds),
            private_values=private_values,
            on_stage_done=on_stage_done,
        )
        rounds.append(round_result)

        on_round(round_result)

    return rounds


def best_round(rounds: list[RoundResult]) -> RoundResult | None:
    """The last accepted round: each acceptance beat the best before it."""
    accepted = [r for r in rounds if r.accepted]
    return accepted[-1] if accepted else None
