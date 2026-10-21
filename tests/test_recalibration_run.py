"""Tests for `screen.recalibration_run` — the resumable run record.

Covers: round-trip of run state through JSON, transcript appends, the default run
directory layout, and the resume refusal when `rubric.yaml` has drifted away from
the baseline the run was measured against.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screen import recalibration as rr
from screen import recalibration_run as run


def _case(pair_id: str = "p1", prediction: str = "b") -> rr.LabeledCase:
    return rr.LabeledCase(
        pair_id=pair_id,
        digest_a="A digest",
        digest_b="B digest",
        expected="a",
        jev_prediction=prediction,
        jev_confidence=0.9,
        sure=True,
        p_clear=0.9,
        p_a=0.1,
    )


def _evaluation(prediction: str = "b") -> rr.EvaluationResult:
    return rr.EvaluationResult.from_cases([_case(prediction=prediction)])


def _round(round_num: int = 1) -> rr.RoundResult:
    baseline = _evaluation()
    return rr.RoundResult(
        round_num=round_num,
        candidate_rubric_text="### Location (slug: location, weight: 6)\nnew",
        held_out_buckets=rr.BucketCounts(right_sure=1),
        theory="theory",
        expected_effect="fewer wrong+sure on tie pairs",
        train_buckets=rr.BucketCounts(right_sure=1),
        train_cases=baseline.cases,
        held_out_cases=baseline.cases,
        fixed_cases=baseline.cases,
        broken_cases=[],
        train_net=1.0,
        train_brier=0.25,
        accepted=True,
    )


def _state(tmp_path: Path, rounds: list[rr.RoundResult] | None = None) -> run.RunState:
    baseline = _evaluation()
    return run.new_run_state(
        run_dir=tmp_path / "run",
        target="location",
        seed=42,
        floor=70,
        context_mode="full",
        baseline_rubric_text="### Location (slug: location, weight: 6)\nbaseline",
        baseline_train=baseline,
        baseline_noise=baseline,
        propose_pairs=[rr.UsablePair("p1", "oa", "ob", "A", "B", "a")],
        held_pairs=[rr.UsablePair("p2", "oc", "od", "C", "D", "b")],
        rounds=rounds or [],
    )


def test_new_run_state_starts_from_baseline_and_lays_out_the_run_dir(tmp_path: Path) -> None:
    state = _state(tmp_path)

    assert state.state_path == tmp_path / "run" / "state.json"
    assert state.transcript_path == tmp_path / "run" / "transcript.jsonl"
    assert state.current_rubric_text == state.baseline_rubric_text
    assert state.current_train is state.baseline_train
    assert state.rounds_completed == 0


def test_save_and_load_round_trips_every_field(tmp_path: Path) -> None:
    state = _state(tmp_path, rounds=[_round()])

    run.save_state(state)
    loaded = run.load_state(state.state_path)

    assert loaded.target == "location"
    assert loaded.seed == 42
    assert loaded.floor == 70
    assert loaded.context_mode == "full"
    assert loaded.baseline_rubric_text == state.baseline_rubric_text
    assert loaded.baseline_train.buckets == state.baseline_train.buckets
    assert loaded.baseline_noise.cases == state.baseline_noise.cases
    assert [p.pair_id for p in loaded.propose_pairs] == ["p1"]
    assert [p.pair_id for p in loaded.held_pairs] == ["p2"]
    assert loaded.rounds[0].theory == "theory"
    assert loaded.rounds[0].expected_effect == "fewer wrong+sure on tie pairs"
    assert loaded.rounds[0].fixed_cases[0].pair_id == "p1"
    assert loaded.rounds[0].accepted is True
    assert loaded.rounds[0].train_net == 1.0
    assert loaded.rounds[0].train_brier == 0.25
    assert loaded.baseline_noise.cases[0].p_a == 0.1
    assert loaded.state_path == state.state_path
    assert loaded.transcript_path == state.transcript_path


def test_load_state_restores_a_round_with_no_train_measurement(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.rounds = [
        rr.RoundResult(
            round_num=1,
            candidate_rubric_text="candidate",
            held_out_buckets=rr.BucketCounts(),
            theory="t",
        )
    ]
    run.save_state(state)

    loaded = run.load_state(state.state_path)
    assert loaded.rounds[0].train_buckets is None
    assert loaded.rounds[0].train_cases == []
    assert loaded.rounds[0].expected_effect == ""


def test_record_round_advances_current_best_only_when_accepted(tmp_path: Path) -> None:
    state = _state(tmp_path)
    improved = rr.EvaluationResult.from_cases([_case(prediction="a")])
    accepted = _round()
    accepted.train_cases = improved.cases
    accepted.train_buckets = improved.buckets

    run.record_round(state, accepted)

    assert state.rounds_completed == 1
    assert state.current_rubric_text == accepted.candidate_rubric_text
    assert state.current_train.cases == improved.cases

    rejected = _round(round_num=2)
    rejected.accepted = False
    rejected.candidate_rubric_text = "### Location (slug: location, weight: 6)\nrejected"
    run.record_round(state, rejected)

    assert state.rounds_completed == 2
    assert state.current_rubric_text == accepted.candidate_rubric_text

    reloaded = run.load_state(state.state_path)
    assert reloaded.rounds_completed == 2
    assert reloaded.current_rubric_text == accepted.candidate_rubric_text

    transcript = state.transcript_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(transcript) == 2
    assert json.loads(transcript[0])["round"]["round_num"] == 1
    assert json.loads(transcript[1])["round"]["accepted"] is False


def test_resume_refuses_when_the_baseline_rubric_has_drifted(tmp_path: Path) -> None:
    state = _state(tmp_path)
    run.save_state(state)

    run.require_baseline_unchanged(state, state.baseline_rubric_text)

    with pytest.raises(run.ResumeRefusedError, match="location"):
        run.require_baseline_unchanged(state, "### Location (slug: location, weight: 6)\nedited")


def test_load_state_refuses_a_run_saved_without_jev_probabilities(tmp_path: Path) -> None:
    """The regression: a pre-Brier state.json loads with no per-case probabilities and
    the run crashes mid-round (or scores against made-up defaults) instead of saying
    the run can't be resumed."""
    state = _state(tmp_path)
    run.save_state(state)
    data = json.loads(state.state_path.read_text(encoding="utf-8"))
    for case in data["baseline_train"]["cases"]:
        del case["p_clear"]
    state.state_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(run.ResumeRefusedError, match="Start a new run"):
        run.load_state(state.state_path)


def test_default_run_dir_is_namespaced_by_target_and_timestamp() -> None:
    run_dir = run.default_run_dir("location", stamp="20261022T120000Z", data_root=Path("data"))
    assert run_dir == Path("data") / "recalibration" / "location" / "20261022T120000Z"
