"""The recalibration run record: the loop's history and its resume state.

These are the same artifact. A run's history — baseline, splits, per-round
candidates and the pairs each one fixed or broke — is what the proposer reads as
OPRO context, and it is also everything needed to continue a run that stopped at
its round budget. Persisting it once serves both.

The record lives under the data directory (gitignored): transcripts quote digest
text, which names real companies.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from screen.recalibration import (
    BucketCounts,
    ConfusionMatrix,
    EvaluationResult,
    LabeledCase,
    RoundResult,
    UnversionedDigests,
    UsablePair,
)
from screen.recalibration import (
    brier_noise_floor as _brier_noise_floor,
)

_STATE_FILENAME = "state.json"
_TRANSCRIPT_FILENAME = "transcript.jsonl"


class ResumeRefusedError(RuntimeError):
    """The run cannot be continued because its premises no longer hold."""


@dataclass
class RunState:
    """One recalibration run, as persisted.

    The splits, baseline and Brier noise floor are pinned at creation and never
    recomputed: new operator rulings would otherwise reshuffle the split for the
    same seed, and re-measuring the baseline both costs Jev calls and moves the
    reference point a resumed run is being compared against.

    `unversioned_digests` is the policy the splits were loaded under. A record saved
    without it was loaded with `LATEST`, the only behavior that existed then.
    """

    run_dir: Path
    target: str
    seed: int
    floor: int
    context_mode: str
    baseline_rubric_text: str
    baseline_train: EvaluationResult
    baseline_noise: EvaluationResult
    current_rubric_text: str
    current_train: EvaluationResult
    propose_pairs: list[UsablePair]
    held_pairs: list[UsablePair]
    unversioned_digests: UnversionedDigests
    rounds: list[RoundResult] = field(default_factory=list[RoundResult])

    @property
    def state_path(self) -> Path:
        return self.run_dir / _STATE_FILENAME

    @property
    def transcript_path(self) -> Path:
        return self.run_dir / _TRANSCRIPT_FILENAME

    @property
    def rounds_completed(self) -> int:
        return len(self.rounds)

    @property
    def brier_noise_floor(self) -> float:
        """Mean-Brier jitter between two evaluations of the same baseline text — the
        gain a candidate needs before its Brier score counts as signal."""
        return _brier_noise_floor(self.baseline_train, self.baseline_noise)


def default_run_dir(
    target: str, *, stamp: str | None = None, data_root: Path | None = None
) -> Path:
    """Timestamped run directory under the data root. `stamp` is injectable so
    tests don't depend on the clock."""
    stamp = stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = data_root if data_root is not None else Path("data")
    return root / "recalibration" / target / stamp


def new_run_state(
    *,
    run_dir: Path,
    target: str,
    seed: int,
    floor: int,
    context_mode: str,
    baseline_rubric_text: str,
    baseline_train: EvaluationResult,
    baseline_noise: EvaluationResult,
    propose_pairs: list[UsablePair],
    held_pairs: list[UsablePair],
    unversioned_digests: UnversionedDigests,
    rounds: list[RoundResult] | None = None,
) -> RunState:
    """A run at round zero: the current best is the baseline."""
    return RunState(
        run_dir=run_dir,
        target=target,
        seed=seed,
        floor=floor,
        context_mode=context_mode,
        baseline_rubric_text=baseline_rubric_text,
        baseline_train=baseline_train,
        baseline_noise=baseline_noise,
        current_rubric_text=baseline_rubric_text,
        current_train=baseline_train,
        propose_pairs=propose_pairs,
        held_pairs=held_pairs,
        unversioned_digests=unversioned_digests,
        rounds=rounds if rounds is not None else [],
    )


def require_baseline_unchanged(state: RunState, current_rubric_text: str) -> None:
    """Refuse to continue a run whose baseline text no longer matches the rubric.

    Every delta in the record is measured against `baseline_rubric_text`. If
    `rubric.yaml` has been edited since, the saved numbers describe text that is
    no longer in the file, and continuing would compare candidates to a baseline
    that was never evaluated.
    """
    if state.baseline_rubric_text != current_rubric_text:
        raise ResumeRefusedError(
            f"{state.target}: rubric.yaml no longer matches the baseline this run was "
            f"measured against ({state.state_path}). Restore the baseline text or start "
            "a new run."
        )


def record_round(state: RunState, round_result: RoundResult) -> None:
    """Append a round, advance the current best if it was accepted, and persist.

    Written after every round rather than at the end so a run killed mid-flight
    is still resumable from its last completed round.
    """
    state.rounds.append(round_result)
    if round_result.accepted:
        state.current_rubric_text = round_result.candidate_rubric_text
        state.current_train = EvaluationResult.from_cases(round_result.train_cases or [])
    _append_transcript(state, round_result)
    save_state(state)


def save_state(state: RunState) -> None:
    state.run_dir.mkdir(parents=True, exist_ok=True)
    state.state_path.write_text(_StateRecord.of(state).model_dump_json(indent=2), encoding="utf-8")


def load_state(state_path: Path) -> RunState:
    text = state_path.read_text(encoding="utf-8")
    raw: Any = json.loads(text)
    if any("p_clear" not in case for case in raw["baseline_train"]["cases"]):
        raise ResumeRefusedError(
            f"{state_path} predates per-case Jev probabilities, which the Brier score "
            "needs. Start a new run."
        )
    record = _StateRecord.model_validate(raw)
    return RunState(
        run_dir=state_path.parent,
        target=record.target,
        seed=record.seed,
        floor=record.floor,
        context_mode=record.context_mode,
        baseline_rubric_text=record.baseline_rubric_text,
        baseline_train=record.baseline_train.result(),
        baseline_noise=record.baseline_noise.result(),
        current_rubric_text=record.current_rubric_text,
        current_train=record.current_train.result(),
        propose_pairs=record.propose_pairs,
        held_pairs=record.held_pairs,
        unversioned_digests=record.unversioned_digests,
        rounds=[item.result() for item in record.rounds],
    )


def _append_transcript(state: RunState, round_result: RoundResult) -> None:
    state.run_dir.mkdir(parents=True, exist_ok=True)
    record = _TranscriptRecord(
        round=_RoundRecord.of(round_result),
        current_rubric_text=state.current_rubric_text,
        current_train=_EvaluationRecord.of(state.current_train),
    )
    with state.transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json())
        handle.write("\n")


class _EvaluationRecord(BaseModel):
    buckets: BucketCounts
    cases: list[LabeledCase]
    confusion: ConfusionMatrix

    @classmethod
    def of(cls, result: EvaluationResult) -> _EvaluationRecord:
        return cls(buckets=result.buckets, cases=result.cases, confusion=result.confusion)

    def result(self) -> EvaluationResult:
        return EvaluationResult(buckets=self.buckets, cases=self.cases, confusion=self.confusion)


class _RoundRecord(BaseModel):
    """A round as persisted. Fields with defaults are absent from records saved before
    they were measured; a round with no train measurement loads with empty case lists."""

    round_num: int
    candidate_rubric_text: str
    held_out_buckets: BucketCounts
    theory: str
    expected_effect: str = ""
    train_buckets: BucketCounts | None = None
    train_cases: list[LabeledCase] = Field(default_factory=list[LabeledCase])
    held_out_cases: list[LabeledCase] = Field(default_factory=list[LabeledCase])
    fixed_cases: list[LabeledCase] = Field(default_factory=list[LabeledCase])
    broken_cases: list[LabeledCase] = Field(default_factory=list[LabeledCase])
    train_net: float = 0.0
    train_brier: float = 0.0
    accepted: bool = False

    @classmethod
    def of(cls, result: RoundResult) -> _RoundRecord:
        return cls(
            round_num=result.round_num,
            candidate_rubric_text=result.candidate_rubric_text,
            held_out_buckets=result.held_out_buckets,
            theory=result.theory,
            expected_effect=result.expected_effect,
            train_buckets=result.train_buckets,
            train_cases=result.train_cases or [],
            held_out_cases=result.held_out_cases or [],
            fixed_cases=result.fixed_cases,
            broken_cases=result.broken_cases,
            train_net=result.train_net,
            train_brier=result.train_brier,
            accepted=result.accepted,
        )

    def result(self) -> RoundResult:
        return RoundResult(
            round_num=self.round_num,
            candidate_rubric_text=self.candidate_rubric_text,
            held_out_buckets=self.held_out_buckets,
            theory=self.theory,
            expected_effect=self.expected_effect,
            train_buckets=self.train_buckets,
            train_cases=self.train_cases,
            held_out_cases=self.held_out_cases,
            fixed_cases=self.fixed_cases,
            broken_cases=self.broken_cases,
            train_net=self.train_net,
            train_brier=self.train_brier,
            accepted=self.accepted,
        )


class _StateRecord(BaseModel):
    """`state.json`. `unversioned_digests` defaults for records saved before it existed."""

    target: str
    seed: int
    floor: int
    context_mode: str
    baseline_rubric_text: str
    baseline_train: _EvaluationRecord
    baseline_noise: _EvaluationRecord
    current_rubric_text: str
    current_train: _EvaluationRecord
    propose_pairs: list[UsablePair]
    held_pairs: list[UsablePair]
    unversioned_digests: UnversionedDigests = UnversionedDigests.LATEST
    rounds: list[_RoundRecord] = Field(default_factory=list[_RoundRecord])

    @classmethod
    def of(cls, state: RunState) -> _StateRecord:
        return cls(
            target=state.target,
            seed=state.seed,
            floor=state.floor,
            context_mode=state.context_mode,
            baseline_rubric_text=state.baseline_rubric_text,
            baseline_train=_EvaluationRecord.of(state.baseline_train),
            baseline_noise=_EvaluationRecord.of(state.baseline_noise),
            current_rubric_text=state.current_rubric_text,
            current_train=_EvaluationRecord.of(state.current_train),
            propose_pairs=state.propose_pairs,
            held_pairs=state.held_pairs,
            unversioned_digests=state.unversioned_digests,
            rounds=[_RoundRecord.of(item) for item in state.rounds],
        )


class _TranscriptRecord(BaseModel):
    round: _RoundRecord
    current_rubric_text: str
    current_train: _EvaluationRecord
