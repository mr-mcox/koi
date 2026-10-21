"""Tests for the rubric recalibration loop.

Covers: eligibility gate, full-digest proposer context, structured proposer output,
partial-draft rehydration, zero-shot Jev evaluation, and paired acceptance. The
resumable run record is covered in `test_recalibration_run.py`.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
import yaml

from screen import recalibration as rr
from screen.extract.prompt import rubric_text_for_dimension
from screen.verdict.protocol import JevRuling, NoulJudgment
from scripts import recalibrate_rubric as cli


class _ClosingConnection(sqlite3.Connection):
    def __del__(self) -> None:  # pragma: no cover - safety net for test cleanup
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE comparisons (
            id TEXT PRIMARY KEY,
            opening_a_id TEXT,
            opening_b_id TEXT,
            target TEXT,
            outcome TEXT,
            provenance TEXT,
            created_at TEXT,
            predicted_a_beats_b REAL,
            opening_a_digest_version TEXT,
            opening_b_digest_version TEXT
        );
        CREATE TABLE dimension_digests (
            id TEXT PRIMARY KEY,
            opening_id TEXT,
            target TEXT,
            digest TEXT,
            assertion_count INTEGER,
            computed_at TEXT
        );
        """)
    return conn


def _insert_pair(
    conn: sqlite3.Connection,
    *,
    pair_id: str,
    target: str,
    outcome: str = "a",
    provenance: str = "operator",
    digest_a: str | None = None,
    digest_b: str | None = None,
) -> None:
    oid_a = f"{pair_id}_a"
    oid_b = f"{pair_id}_b"
    conn.execute(
        "INSERT INTO comparisons VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            pair_id,
            oid_a,
            oid_b,
            target,
            outcome,
            provenance,
            "2026-01-01T00:00:00",
            0.5,
            None,
            None,
        ),
    )
    for oid, label in [
        (oid_a, digest_a or f"digest-a for {pair_id}"),
        (oid_b, digest_b or f"digest-b for {pair_id}"),
    ]:
        conn.execute(
            "INSERT INTO dimension_digests VALUES (?,?,?,?,?,?)",
            (f"{oid}-{target}", oid, target, label, 1, "2026-01-01T00:00:00"),
        )
    conn.commit()


def _pair_cases(
    *,
    pair_id: str,
    expected: str,
    prediction: str,
    sure: bool,
    digest_a: str = "A digest",
    digest_b: str = "B digest",
    confidence: float = 0.9,
) -> rr.LabeledCase:
    return rr.LabeledCase(
        pair_id=pair_id,
        digest_a=digest_a,
        digest_b=digest_b,
        expected=expected,
        jev_prediction=prediction,
        jev_confidence=confidence,
        sure=sure,
    )


def _eval_result(cases: list[rr.LabeledCase]) -> rr.EvaluationResult:
    return rr.EvaluationResult.from_cases(cases)


# ---------------------------------------------------------------------------
# Eligibility gate
# ---------------------------------------------------------------------------


def test_load_pairs_rejects_target_below_floor() -> None:
    conn = _make_conn()
    for i in range(5):
        _insert_pair(conn, pair_id=f"p{i}", target="trajectory")

    pairs, shortfall = rr.load_pairs(conn, target="trajectory", floor=70)
    assert pairs == []
    assert shortfall == 65
    conn.close()


def test_load_pairs_accepts_target_at_floor_and_skips_non_operator() -> None:
    conn = _make_conn()
    for i in range(70):
        _insert_pair(conn, pair_id=f"p{i}", target="location", provenance="operator")
    for i in range(10):
        _insert_pair(conn, pair_id=f"prov{i}", target="location", provenance="provisional")

    pairs, shortfall = rr.load_pairs(conn, target="location", floor=70)
    assert len(pairs) == 70
    assert shortfall == 0
    conn.close()


# ---------------------------------------------------------------------------
# Proposer context and rendering
# ---------------------------------------------------------------------------


_BASELINE_RUBRIC = """### Location compatibility (slug: location, weight: 6)
old definition
Fit anchors:
  Poor: Relocation required.
  Mixed: Remote offered but travel unclear.
  Strong: Distributed / remote-first.
Look for: Explicit remote policy language."""


def test_render_candidate_text_keeps_heading_and_omits_proposer_reasoning() -> None:
    proposal = rr.RubricProposal(
        theory="fix the offsite travel signal",
        expected_effect="more right+sure on remote-vs-hybrid pairs",
        definition="A new definition line.",
        fit_anchor_poor="Bad evidence.",
        fit_anchor_mixed="Mixed evidence.",
        fit_anchor_strong="Strong evidence.",
        look_for="Look for explicit remote policy.",
    )
    candidate = rr.render_candidate_text(_BASELINE_RUBRIC, proposal)
    assert candidate.startswith("### Location compatibility (slug: location, weight: 6)")
    assert "A new definition line." in candidate
    assert "fix the offsite travel signal" not in candidate
    assert "more right+sure" not in candidate


def test_render_candidate_text_rehydrates_fields_the_proposer_left_alone() -> None:
    """A proposer editing one anchor must not have to retype the untouched fields."""
    proposal = rr.RubricProposal(
        theory="only the Mixed anchor is wrong",
        expected_effect="fewer wrong+sure ties",
        fit_anchor_mixed="Remote offered but the posting is silent on travel.",
    )
    candidate = rr.render_candidate_text(_BASELINE_RUBRIC, proposal)

    assert "old definition" in candidate
    assert "Poor: Relocation required." in candidate
    assert "Mixed: Remote offered but the posting is silent on travel." in candidate
    assert "Strong: Distributed / remote-first." in candidate
    assert "Look for: Explicit remote policy language." in candidate


def test_render_candidate_text_of_an_empty_proposal_reproduces_the_baseline() -> None:
    """The no-op candidate must be byte-identical, or the loop measures formatting."""
    proposal = rr.RubricProposal(theory="no wording defect found", expected_effect="nothing")
    assert rr.render_candidate_text(_BASELINE_RUBRIC, proposal) == _BASELINE_RUBRIC


def test_render_candidate_text_round_trips_the_live_rubric_text() -> None:
    """Guards the live shape: `rubric_text_for_dimension` leads with a blank line, and
    an unedited proposal must reproduce it exactly or every candidate pays a formatting
    penalty Jev reads as a rubric change."""
    live = rubric_text_for_dimension("location")
    proposal = rr.RubricProposal(theory="no edit", expected_effect="nothing")
    assert rr.render_candidate_text(live, proposal) == live


def test_anthropic_proposer_shows_full_digests_and_maps_structured_output() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def ProposeRubricEdit(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                theory="theory sentence",
                expected_effect="fewer wrong+sure on tie pairs",
                definition="definition draft",
                fit_anchor_poor="poor draft",
                fit_anchor_mixed="mixed draft",
                fit_anchor_strong="strong draft",
                look_for="look for draft",
            )

    long_a = "A" * 140
    long_b = "B" * 145
    fake_client = FakeClient()
    proposer = cli.AnthropicProposer(context_mode="sampled", client=fake_client)
    cases = [
        _pair_cases(
            pair_id="p1",
            expected="a",
            prediction="b",
            sure=True,
            digest_a=long_a,
            digest_b=long_b,
        ),
        _pair_cases(
            pair_id="p2",
            expected="a",
            prediction="a",
            sure=False,
            digest_a="short-a",
            digest_b="short-b",
        ),
    ]
    proposal = proposer.propose(
        current_rubric_text="### Location compatibility (slug: location, weight: 6)\nold",
        labeled_cases=cases,
        prior_rounds=[],
    )

    assert proposal.theory == "theory sentence"
    assert proposal.expected_effect == "fewer wrong+sure on tie pairs"
    call = fake_client.calls[0]
    assert long_b in call["current_cases_text"]
    assert "..." not in call["current_cases_text"]


# ---------------------------------------------------------------------------
# Jev evaluation and paired acceptance
# ---------------------------------------------------------------------------


def test_evaluator_uses_zero_shot_and_live_thresholds() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[list] = []

        def get_ruling(
            self, rubric_text: str, digest_a: str, digest_b: str, few_shot_examples: list
        ):
            self.calls.append(few_shot_examples)
            if (digest_a, digest_b) == ("A1", "B1"):
                return JevRuling(
                    clear_winner=NoulJudgment(p_true=0.9),
                    a_is_better=NoulJudgment(p_true=0.9),
                )
            return JevRuling(
                clear_winner=NoulJudgment(p_true=0.8),
                a_is_better=NoulJudgment(p_true=0.1),
            )

    config = SimpleNamespace(tie_commit_threshold=0.95, winner_commit_threshold=0.85)
    fake_provider = FakeProvider()
    evaluator = cli.JevEvaluator(fake_provider, config)

    result = evaluator.evaluate(
        [rr.UsablePair("p1", "oa", "ob", "A1", "B1", "a")],
        "rubric text",
    )
    assert result.buckets.right_sure == 1
    assert result.cases[0].jev_prediction == "a"
    assert result.cases[0].sure is True
    assert fake_provider.calls == [[], []]


class FakeProposer:
    def __init__(self, proposals: list[rr.RubricProposal]) -> None:
        self._proposals = proposals
        self.calls: list[dict] = []
        self._index = 0

    def propose(
        self,
        *,
        current_rubric_text: str,
        labeled_cases: list[rr.LabeledCase],
        prior_rounds: list[rr.RoundResult],
    ) -> rr.RubricProposal:
        self.calls.append(
            {
                "current_rubric_text": current_rubric_text,
                "labeled_cases": labeled_cases,
                "prior_rounds": prior_rounds,
            }
        )
        proposal = self._proposals[min(self._index, len(self._proposals) - 1)]
        self._index += 1
        return proposal


class FakeEvaluator:
    def __init__(self, results: list[rr.EvaluationResult]) -> None:
        self._results = results
        self._index = 0

    def evaluate(self, pairs: list[rr.UsablePair], rubric_text: str) -> rr.EvaluationResult:
        result = self._results[min(self._index, len(self._results) - 1)]
        self._index += 1
        return result


def test_run_rounds_records_history_and_uses_paired_acceptance() -> None:
    pairs = [
        rr.UsablePair("p1", "oa1", "ob1", "A1", "B1", "a"),
        rr.UsablePair("p2", "oa2", "ob2", "A2", "B2", "b"),
    ]
    baseline_cases = [
        _pair_cases(pair_id="p1", expected="a", prediction="b", sure=True),
        _pair_cases(pair_id="p2", expected="b", prediction="b", sure=True),
    ]
    improved_cases = [
        _pair_cases(pair_id="p1", expected="a", prediction="a", sure=True),
        _pair_cases(pair_id="p2", expected="b", prediction="b", sure=True),
    ]
    worse_cases = [
        _pair_cases(pair_id="p1", expected="a", prediction="b", sure=True),
        _pair_cases(pair_id="p2", expected="b", prediction="a", sure=True),
    ]
    baseline_train = _eval_result(baseline_cases)
    baseline_noise = _eval_result(baseline_cases)
    proposer = FakeProposer(
        [
            rr.RubricProposal(
                theory="theory 1",
                expected_effect="effect 1",
                definition="definition 1",
                fit_anchor_poor="poor 1",
                fit_anchor_mixed="mixed 1",
                fit_anchor_strong="strong 1",
                look_for="look 1",
            ),
            rr.RubricProposal(
                theory="theory 2",
                expected_effect="effect 2",
                definition="definition 2",
                fit_anchor_poor="poor 2",
                fit_anchor_mixed="mixed 2",
                fit_anchor_strong="strong 2",
                look_for="look 2",
            ),
        ]
    )
    evaluator = FakeEvaluator(
        [
            _eval_result(improved_cases),
            _eval_result([_pair_cases(pair_id="p1", expected="a", prediction="a", sure=True)]),
            _eval_result(worse_cases),
            _eval_result(worse_cases),
        ]
    )

    rounds = rr.run_rounds(
        propose_pairs=pairs,
        held_pairs=pairs,
        labeled_cases=baseline_train.cases,
        current_rubric_text="### Location compatibility (slug: location, weight: 6)\nold",
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=2,
        baseline_train=baseline_train,
        baseline_noise=baseline_noise,
        noise_floor_delta=0,
    )

    assert len(rounds) == 2
    assert rounds[0].accepted is True
    assert rounds[0].candidate_delta == 1
    assert len(rounds[0].fixed_cases) == 1
    assert len(rounds[0].broken_cases) == 0
    assert rounds[1].accepted is False
    assert proposer.calls[1]["prior_rounds"][0] is rounds[0]
    assert proposer.calls[1]["labeled_cases"][0].jev_prediction == "a"


def test_confusion_matrix_and_bucket_counts_cover_all_outcomes() -> None:
    cases = [
        _pair_cases(pair_id="p1", expected="a", prediction="a", sure=True),
        _pair_cases(pair_id="p2", expected="a", prediction="a", sure=False),
        _pair_cases(pair_id="p3", expected="a", prediction="b", sure=True),
        _pair_cases(pair_id="p4", expected="a", prediction="b", sure=False),
        _pair_cases(pair_id="p5", expected="tie", prediction="tie", sure=False),
    ]
    evaluation = _eval_result(cases)
    assert evaluation.buckets.right_sure == 1
    assert evaluation.buckets.right_unsure == 2
    assert evaluation.buckets.wrong_sure == 1
    assert evaluation.buckets.wrong_unsure == 1
    assert evaluation.buckets.total == 5
    assert evaluation.buckets.precision_when_sure == 1 / 2
    assert str(evaluation.buckets).startswith("right+sure")
    assert str(evaluation.confusion).startswith("expected a")
    with pytest.raises(ValueError):
        rr.ConfusionMatrix.from_cases(
            [_pair_cases(pair_id="bad", expected="x", prediction="a", sure=False)]
        )


def test_bucket_counts_precision_when_sure_handles_empty_denominator() -> None:
    assert rr.BucketCounts().precision_when_sure == 0.0


def test_load_pairs_skips_missing_digest_and_split_pairs_is_deterministic() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")
    conn.execute("DELETE FROM dimension_digests WHERE opening_id = 'p0_a'")
    conn.commit()

    pairs, shortfall = rr.load_pairs(conn, target="location", floor=70)
    assert shortfall == 0
    assert len(pairs) == 79

    propose_a, held_a = rr.split_pairs(pairs, seed=42)
    propose_b, held_b = rr.split_pairs(pairs, seed=42)
    assert [p.pair_id for p in propose_a] == [p.pair_id for p in propose_b]
    assert [p.pair_id for p in held_a] == [p.pair_id for p in held_b]
    conn.close()


def test_render_candidate_text_requires_heading() -> None:
    proposal = rr.RubricProposal(theory="t", expected_effect="e", definition="d")
    with pytest.raises(ValueError, match="heading"):
        rr.render_candidate_text("old body only", proposal)


def test_evaluation_result_diff_against_and_best_round_fallback() -> None:
    a = _eval_result([_pair_cases(pair_id="p1", expected="a", prediction="b", sure=False)])
    b = _eval_result([_pair_cases(pair_id="p1", expected="a", prediction="a", sure=True)])
    delta = b.diff_against(a)
    assert delta.delta == 1
    assert len(delta.fixed) == 1

    with pytest.raises(ValueError):
        b.diff_against(
            _eval_result([_pair_cases(pair_id="other", expected="a", prediction="a", sure=True)])
        )


def test_best_round_returns_last_accepted_round() -> None:
    baseline = rr.BucketCounts(right_sure=1)
    rounds = [
        rr.RoundResult(
            round_num=1,
            candidate_rubric_text="short",
            held_out_buckets=rr.BucketCounts(),
            theory="t1",
            train_buckets=rr.BucketCounts(right_sure=1),
            accepted=True,
        ),
        rr.RoundResult(
            round_num=2,
            candidate_rubric_text="longer",
            held_out_buckets=rr.BucketCounts(),
            theory="t2",
            train_buckets=rr.BucketCounts(right_sure=2),
            accepted=True,
        ),
    ]
    winner = rr.best_round(rounds, baseline, "baseline rubric")
    assert winner is not None
    assert winner.round_num == 2


def test_best_round_picks_best_scored_round_when_none_accepted() -> None:
    baseline = rr.BucketCounts(right_sure=1)
    rounds = [
        rr.RoundResult(
            round_num=1,
            candidate_rubric_text="short",
            held_out_buckets=rr.BucketCounts(),
            theory="t1",
            train_buckets=rr.BucketCounts(right_sure=2),
        ),
        rr.RoundResult(
            round_num=2,
            candidate_rubric_text="longer",
            held_out_buckets=rr.BucketCounts(),
            theory="t2",
            train_buckets=rr.BucketCounts(right_sure=3),
        ),
    ]
    winner = rr.best_round(rounds, baseline, "baseline rubric")
    assert winner is not None
    assert winner.round_num == 2


def test_best_round_returns_none_when_no_round_beats_baseline() -> None:
    baseline = rr.BucketCounts(right_sure=1)
    rounds = [
        rr.RoundResult(
            round_num=1,
            candidate_rubric_text="a much longer rubric text",
            held_out_buckets=rr.BucketCounts(),
            theory="t1",
            train_buckets=rr.BucketCounts(right_sure=1),
        )
    ]
    assert rr.best_round(rounds, baseline, "baseline rubric") is None


def test_run_rounds_numbers_rounds_after_a_resume() -> None:
    """A resumed run continues the round numbering, so the transcript and the
    proposer's history don't restart at 1 and collide with earlier rounds."""
    pairs = [rr.UsablePair("p1", "oa1", "ob1", "A1", "B1", "a")]
    baseline = _eval_result([_pair_cases(pair_id="p1", expected="a", prediction="a", sure=True)])
    proposer = FakeProposer([rr.RubricProposal(theory="t", expected_effect="e", definition="d")])
    evaluator = FakeEvaluator([baseline, baseline, baseline, baseline])

    rounds = rr.run_rounds(
        propose_pairs=pairs,
        held_pairs=pairs,
        labeled_cases=baseline.cases,
        current_rubric_text=_BASELINE_RUBRIC,
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=2,
        baseline_train=baseline,
        baseline_noise=baseline,
        noise_floor_delta=0,
        round_offset=3,
    )

    assert [r.round_num for r in rounds] == [4, 5]


def test_run_rounds_uses_noise_floor_and_on_round_callback() -> None:
    pairs = [rr.UsablePair("p1", "oa1", "ob1", "A1", "B1", "a")]
    baseline_cases = [_pair_cases(pair_id="p1", expected="a", prediction="a", sure=True)]
    baseline_train = _eval_result(baseline_cases)
    baseline_noise = _eval_result(baseline_cases)
    proposer = FakeProposer(
        [rr.RubricProposal(theory="t", expected_effect="e", definition="short")]
    )
    evaluator = FakeEvaluator(
        [
            baseline_train,
            baseline_noise,
            _eval_result(baseline_cases),
            _eval_result(baseline_cases),
        ]
    )
    seen: list[int] = []

    rounds = rr.run_rounds(
        propose_pairs=pairs,
        held_pairs=pairs,
        labeled_cases=baseline_train.cases,
        current_rubric_text="""### Location compatibility (slug: location, weight: 6)
very long baseline body that is deliberately much longer than the candidate draft.
Fit anchors:
  Poor: lots of words that make the baseline long.
  Mixed: lots of words that make the baseline long.
  Strong: lots of words that make the baseline long.
Look for: lots of words that make the baseline long.
""",
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=1,
        on_round=lambda round_result: seen.append(round_result.round_num),
    )

    assert rounds[0].accepted is True
    assert rounds[0].candidate_delta == 0
    assert seen == [1]


# ---------------------------------------------------------------------------
# Candidate parsing and privacy gate
# ---------------------------------------------------------------------------


def test_apply_candidate_writes_every_field_back_to_the_rubric(tmp_path) -> None:
    """A candidate reaching rubric.yaml must land as structured fields, not as one
    blob — the anchors are separate keys the rest of the system reads."""
    rubric_path = tmp_path / "rubric.yaml"
    rubric_path.write_text(
        "dimensions:\n"
        "- slug: location\n"
        "  label: Location compatibility\n"
        "  weight: 6\n"
        "  definition: old definition\n"
        "  fit_anchors:\n"
        "    Poor: old poor\n"
        "    Mixed: old mixed\n"
        "    Strong: old strong\n"
        "  look_for: old look for\n",
        encoding="utf-8",
    )
    candidate = "\n".join(
        [
            "### Location compatibility (slug: location, weight: 6)",
            "new definition",
            "Fit anchors:",
            "  Poor: new poor",
            "  Mixed: new mixed",
            "  Strong: new strong",
            "Look for: new look for",
        ]
    )

    cli.apply_candidate("location", candidate, rubric_path=rubric_path)

    written = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    dim = written["dimensions"][0]
    assert dim["definition"] == "new definition"
    assert dim["fit_anchors"] == {"Poor": "new poor", "Mixed": "new mixed", "Strong": "new strong"}
    assert dim["look_for"] == "new look for"


def test_privacy_gate_rejects_candidate_with_salary_figure() -> None:
    with pytest.raises(rr.PrivacyViolationError, match="230"):
        rr.validate_candidate("Anchors: below $230,000 is Poor; above is Strong.")


def test_privacy_gate_accepts_clean_candidate() -> None:
    rr.validate_candidate("""fit_anchors:
  Poor: Relocation required.
  Mixed: Remote offered but team is centrally based.
  Strong: Distributed-first company.
""")
