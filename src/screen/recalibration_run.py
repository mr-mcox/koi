"""The recalibration run record: the loop's history and its resume state.

These are the same artifact. A run's history — baseline, splits, per-round
candidates and the pairs each one fixed or broke — is what the proposer reads as
OPRO context, and it is also everything needed to continue a run that stopped at
its round budget. Persisting it once serves both.

The record lives under the data directory (gitignored): transcripts quote digest
text, which names real companies.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from screen.recalibration import (
    BucketCounts,
    ConfusionMatrix,
    EvaluationResult,
    LabeledCase,
    RoundResult,
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
    rounds: list[RoundResult] = field(default_factory=list)

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
    state.state_path.write_text(json.dumps(_state_to_dict(state), indent=2), encoding="utf-8")


def load_state(state_path: Path) -> RunState:
    data = json.loads(state_path.read_text(encoding="utf-8"))
    if any("p_clear" not in case for case in data["baseline_train"]["cases"]):
        raise ResumeRefusedError(
            f"{state_path} predates per-case Jev probabilities, which the Brier score "
            "needs. Start a new run."
        )
    return RunState(
        run_dir=state_path.parent,
        target=data["target"],
        seed=int(data["seed"]),
        floor=int(data["floor"]),
        context_mode=data["context_mode"],
        baseline_rubric_text=data["baseline_rubric_text"],
        baseline_train=_evaluation_from_dict(data["baseline_train"]),
        baseline_noise=_evaluation_from_dict(data["baseline_noise"]),
        current_rubric_text=data["current_rubric_text"],
        current_train=_evaluation_from_dict(data["current_train"]),
        propose_pairs=[UsablePair(**item) for item in data["propose_pairs"]],
        held_pairs=[UsablePair(**item) for item in data["held_pairs"]],
        rounds=[_round_from_dict(item) for item in data.get("rounds", [])],
    )


def _append_transcript(state: RunState, round_result: RoundResult) -> None:
    state.run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "round": _round_to_dict(round_result),
        "current_rubric_text": state.current_rubric_text,
        "current_train": _evaluation_to_dict(state.current_train),
    }
    with state.transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record))
        handle.write("\n")


def _state_to_dict(state: RunState) -> dict:
    return {
        "target": state.target,
        "seed": state.seed,
        "floor": state.floor,
        "context_mode": state.context_mode,
        "baseline_rubric_text": state.baseline_rubric_text,
        "baseline_train": _evaluation_to_dict(state.baseline_train),
        "baseline_noise": _evaluation_to_dict(state.baseline_noise),
        "current_rubric_text": state.current_rubric_text,
        "current_train": _evaluation_to_dict(state.current_train),
        "propose_pairs": [asdict(pair) for pair in state.propose_pairs],
        "held_pairs": [asdict(pair) for pair in state.held_pairs],
        "rounds": [_round_to_dict(item) for item in state.rounds],
    }


def _evaluation_to_dict(result: EvaluationResult) -> dict:
    return {
        "buckets": asdict(result.buckets),
        "cases": [asdict(case) for case in result.cases],
        "confusion": asdict(result.confusion),
    }


def _evaluation_from_dict(data: dict) -> EvaluationResult:
    return EvaluationResult(
        buckets=BucketCounts(**data["buckets"]),
        cases=[LabeledCase(**item) for item in data["cases"]],
        confusion=ConfusionMatrix(**data["confusion"]),
    )


def _round_to_dict(result: RoundResult) -> dict:
    return {
        "round_num": result.round_num,
        "candidate_rubric_text": result.candidate_rubric_text,
        "held_out_buckets": asdict(result.held_out_buckets),
        "theory": result.theory,
        "expected_effect": result.expected_effect,
        "train_buckets": asdict(result.train_buckets) if result.train_buckets else None,
        "train_cases": [asdict(case) for case in result.train_cases or []],
        "held_out_cases": [asdict(case) for case in result.held_out_cases or []],
        "fixed_cases": [asdict(case) for case in result.fixed_cases],
        "broken_cases": [asdict(case) for case in result.broken_cases],
        "train_net": result.train_net,
        "train_brier": result.train_brier,
        "accepted": result.accepted,
    }


def _round_from_dict(data: dict) -> RoundResult:
    train_buckets = data.get("train_buckets")
    return RoundResult(
        round_num=int(data["round_num"]),
        candidate_rubric_text=data["candidate_rubric_text"],
        held_out_buckets=BucketCounts(**data["held_out_buckets"]),
        theory=data["theory"],
        expected_effect=data.get("expected_effect", ""),
        train_buckets=BucketCounts(**train_buckets) if train_buckets else None,
        train_cases=[LabeledCase(**item) for item in data.get("train_cases", [])],
        held_out_cases=[LabeledCase(**item) for item in data.get("held_out_cases", [])],
        fixed_cases=[LabeledCase(**item) for item in data.get("fixed_cases", [])],
        broken_cases=[LabeledCase(**item) for item in data.get("broken_cases", [])],
        train_net=float(data.get("train_net", 0.0)),
        train_brier=float(data.get("train_brier", 0.0)),
        accepted=bool(data.get("accepted", False)),
    )
