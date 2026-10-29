"""Tests for the rubric recalibration loop.

Covers: eligibility gate, full-digest proposer context, structured proposer output,
partial-draft rehydration, zero-shot Jev evaluation, and paired acceptance. The
resumable run record is covered in `test_recalibration_run.py`.
"""

import math
import sqlite3
import statistics
from types import SimpleNamespace

import pytest
import yaml

from screen import recalibration as rr
from screen.verdict.protocol import JevRuling, NoulJudgment
from scripts import recalibrate_rubric as cli
from tests.helpers import synthetic_rubric


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
    record_versions: bool = True,
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
            f"{oid_a}-{target}" if record_versions else None,
            f"{oid_b}-{target}" if record_versions else None,
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
    p_clear: float = 0.9,
    p_a: float = 0.9,
) -> rr.LabeledCase:
    return rr.LabeledCase(
        pair_id=pair_id,
        digest_a=digest_a,
        digest_b=digest_b,
        expected=expected,
        jev_prediction=prediction,
        jev_confidence=confidence,
        sure=sure,
        p_clear=p_clear,
        p_a=p_a,
    )


_COSTS = rr.CommitCosts(k_winner=3.0, k_tie=5.0)


def _eval_result(cases: list[rr.LabeledCase]) -> rr.EvaluationResult:
    return rr.EvaluationResult.from_cases(cases)


# ---------------------------------------------------------------------------
# Eligibility gate
# ---------------------------------------------------------------------------


def test_load_pairs_rejects_target_below_floor() -> None:
    conn = _make_conn()
    for i in range(5):
        _insert_pair(conn, pair_id=f"p{i}", target="trajectory")

    loaded = rr.load_pairs(conn, target="trajectory", floor=70)
    assert loaded.pairs == []
    assert loaded.shortfall == 65
    conn.close()


def test_load_pairs_accepts_target_at_floor_and_skips_non_operator() -> None:
    conn = _make_conn()
    for i in range(70):
        _insert_pair(conn, pair_id=f"p{i}", target="location", provenance="operator")
    for i in range(10):
        _insert_pair(conn, pair_id=f"prov{i}", target="location", provenance="provisional")

    loaded = rr.load_pairs(conn, target="location", floor=70)
    assert len(loaded.pairs) == 70
    assert loaded.shortfall == 0
    conn.close()


def _supersede_digest(conn: sqlite3.Connection, opening_id: str, target: str, text: str) -> None:
    conn.execute(
        "INSERT INTO dimension_digests VALUES (?,?,?,?,?,?)",
        (f"{opening_id}-{target}-v2", opening_id, target, text, 2, "2026-02-01T00:00:00"),
    )
    conn.commit()


def test_load_pairs_replays_the_digest_version_the_operator_judged() -> None:
    """The regression: reading the latest digest replays Jev against evidence gathered
    after the ruling, so the case is labeled with a judgment of a different digest."""
    conn = _make_conn()
    _insert_pair(conn, pair_id="p0", target="location", digest_a="judged a")
    _supersede_digest(conn, "p0_a", "location", "newer a")

    loaded = rr.load_pairs(conn, target="location", floor=1)

    assert loaded.pairs[0].digest_a == "judged a"
    assert loaded.unversioned == 0
    conn.close()


def _versioned_and_unversioned_pairs() -> sqlite3.Connection:
    conn = _make_conn()
    _insert_pair(conn, pair_id="old", target="location", record_versions=False)
    _supersede_digest(conn, "old_a", "location", "newer a")
    _insert_pair(conn, pair_id="new", target="location")
    return conn


def test_load_pairs_replays_the_latest_digest_for_an_unversioned_comparison_by_default() -> None:
    conn = _versioned_and_unversioned_pairs()

    loaded = rr.load_pairs(conn, target="location", floor=2)

    by_id = {pair.pair_id: pair for pair in loaded.pairs}
    assert by_id["old"].digest_a == "newer a"
    assert loaded.unversioned == 1
    conn.close()


def test_load_pairs_drops_unversioned_comparisons_when_excluded() -> None:
    conn = _versioned_and_unversioned_pairs()

    loaded = rr.load_pairs(
        conn, target="location", floor=1, unversioned=rr.UnversionedDigests.EXCLUDE
    )

    assert [pair.pair_id for pair in loaded.pairs] == ["new"]
    assert loaded.unversioned == 0
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
    """Guards the live shape: `RubricText.for_dimension` leads with a blank line, and
    an unedited proposal must reproduce it exactly or every candidate pays a formatting
    penalty Jev reads as a rubric change."""
    live = synthetic_rubric().for_dimension("location")
    proposal = rr.RubricProposal(theory="no edit", expected_effect="nothing")
    assert rr.render_candidate_text(live, proposal) == live


def test_structure_rubric_text_uses_the_proposers_own_field_names() -> None:
    """The regression: rendering the dimension as prose (`Mixed: ...`) invited the
    proposer to echo the label back into the value, which landed in rubric.yaml as
    `Mixed: Mixed: ...`."""
    payload = yaml.safe_load(cli.AnthropicProposer._structure_rubric_text(_BASELINE_RUBRIC))
    assert set(payload) == {
        "definition",
        "fit_anchor_poor",
        "fit_anchor_mixed",
        "fit_anchor_strong",
        "look_for",
    }
    live = rr.parse_rubric_fields(synthetic_rubric().for_dimension("location"))
    assert payload["fit_anchor_mixed"] == live["fit_anchor_mixed"]
    assert not payload["fit_anchor_mixed"].startswith("Mixed:")


def test_structure_rubric_text_accepts_a_leading_blank_line() -> None:
    payload = yaml.safe_load(cli.AnthropicProposer._structure_rubric_text("\n" + _BASELINE_RUBRIC))
    assert (
        payload["fit_anchor_mixed"]
        == rr.parse_rubric_fields(synthetic_rubric().for_dimension("location"))["fit_anchor_mixed"]
    )


def test_structure_rubric_text_rejects_text_without_a_dimension_heading() -> None:
    with pytest.raises(ValueError, match="does not start with a dimension heading"):
        cli.AnthropicProposer._structure_rubric_text("old definition\nFit anchors:")


def test_structure_rubric_text_rejects_a_slug_absent_from_rubric_yaml() -> None:
    with pytest.raises(ValueError, match="no dimension with slug 'no-such-slug'"):
        cli.AnthropicProposer._structure_rubric_text(
            "### Nope (slug: no-such-slug, weight: 6)\nbody"
        )


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
    proposer = cli.AnthropicProposer(
        costs=rr.CommitCosts.from_thresholds(
            winner_commit_threshold=0.75, tie_commit_threshold=0.85
        ),
        private_values={},
        brier_floor=0.0123,
        context_mode="sampled",
        client=fake_client,
    )
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
    assert "p_ruling=" in call["current_cases_text"]
    assert "3.00 x (wrong+sure a/b calls)" in call["scoring_rule_text"]
    assert "5.67 x (wrong+sure tie calls)" in call["scoring_rule_text"]
    assert "0.0123" in call["scoring_rule_text"]


def test_anthropic_proposer_retries_empty_text_responses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Also guards the failure log's elapsed time: BAML v0 timeout errors don't say
    which limit fired, so the duration is the only way to tell."""

    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def ProposeRubricEdit(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Anthropic response contains no text")
            return SimpleNamespace(
                theory="theory sentence",
                expected_effect="fewer wrong+sure on tie pairs",
                definition="definition draft",
                fit_anchor_poor=None,
                fit_anchor_mixed=None,
                fit_anchor_strong=None,
                look_for=None,
            )

    ticks = iter([0.0, 312.0, 400.0, 401.0])
    proposer = cli.AnthropicProposer(
        costs=_COSTS,
        private_values={},
        brier_floor=0.0,
        context_mode="sampled",
        client=FlakyClient(),
        clock=lambda: next(ticks),
    )
    proposal = proposer.propose(
        current_rubric_text=_BASELINE_RUBRIC,
        labeled_cases=[],
        prior_rounds=[],
    )
    assert proposal.theory == "theory sentence"
    assert proposal.definition == "definition draft"
    assert "attempt 1/3 failed after 312s" in capsys.readouterr().err


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
    evaluator = cli.JevEvaluator(fake_provider, config, resolve=lambda text: text)

    result = evaluator.evaluate(
        [rr.UsablePair("p1", "oa", "ob", "A1", "B1", "a")],
        "rubric text",
    )
    assert result.buckets.right_sure == 1
    assert result.cases[0].jev_prediction == "a"
    assert result.cases[0].sure is True
    assert result.cases[0].p_clear == pytest.approx(0.85)
    assert result.cases[0].p_a == pytest.approx(0.9)
    assert fake_provider.calls == [[], []]


def test_evaluator_resolves_placeholders_only_for_the_jev_call() -> None:
    """The regression: the run carries unresolved text so the private value never reaches
    the proposer or rubric.yaml; if the evaluator forwarded it as-is, Jev would score
    compensation against a variable name instead of the baseline."""
    seen: list[str] = []

    class FakeProvider:
        def get_ruling(
            self, rubric_text: str, digest_a: str, digest_b: str, few_shot_examples: list
        ):
            seen.append(rubric_text)
            return JevRuling(
                clear_winner=NoulJudgment(p_true=0.1), a_is_better=NoulJudgment(p_true=0.5)
            )

    config = SimpleNamespace(tie_commit_threshold=0.95, winner_commit_threshold=0.85)
    evaluator = cli.JevEvaluator(
        FakeProvider(), config, resolve=lambda text: text.replace("PLACEHOLDER", "42")
    )

    evaluator.evaluate([rr.UsablePair("p1", "oa", "ob", "A1", "B1", "tie")], "above PLACEHOLDER")

    assert seen == ["above 42", "above 42"]


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


def test_run_rounds_records_history_and_accepts_on_net() -> None:
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
        current_rubric_text="### Location compatibility (slug: location, weight: 6)\nold",
        proposer=proposer,
        evaluator=evaluator,
        costs=_COSTS,
        brier_floor=0.0,
        private_values={},
        n_rounds=2,
        baseline_train=baseline_train,
    )

    assert len(rounds) == 2
    assert rounds[0].accepted is True
    assert rounds[0].train_net == 2.0
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

    loaded = rr.load_pairs(conn, target="location", floor=70)
    pairs = loaded.pairs
    assert loaded.shortfall == 0
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


def test_render_candidate_text_omits_missing_look_for_and_parse_fields() -> None:
    rubric = """### Location compatibility (slug: location, weight: 6)
old definition
Fit anchors:
  Poor: old poor
  Mixed: old mixed
  Strong: old strong
"""
    fields = rr.parse_rubric_fields(rubric)
    assert "look_for" not in fields

    proposal = rr.RubricProposal(theory="t", expected_effect="e", definition="d")
    rendered = rr.render_candidate_text(rubric, proposal)
    assert "Look for:" not in rendered


def test_evaluation_result_diff_against() -> None:
    a = _eval_result([_pair_cases(pair_id="p1", expected="a", prediction="b", sure=False)])
    b = _eval_result([_pair_cases(pair_id="p1", expected="a", prediction="a", sure=True)])
    delta = b.diff_against(a)
    assert len(delta.fixed) == 1
    assert delta.broken == []

    with pytest.raises(ValueError):
        b.diff_against(
            _eval_result([_pair_cases(pair_id="other", expected="a", prediction="a", sure=True)])
        )


def _round(round_num: int, *, accepted: bool) -> rr.RoundResult:
    return rr.RoundResult(
        round_num=round_num,
        candidate_rubric_text=f"text {round_num}",
        held_out_buckets=rr.BucketCounts(),
        theory=f"t{round_num}",
        accepted=accepted,
    )


def test_best_round_returns_last_accepted_round() -> None:
    rounds = [_round(1, accepted=True), _round(2, accepted=True), _round(3, accepted=False)]
    winner = rr.best_round(rounds)
    assert winner is not None
    assert winner.round_num == 2


def test_best_round_returns_none_when_nothing_was_accepted() -> None:
    assert rr.best_round([_round(1, accepted=False)]) is None


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
        current_rubric_text=_BASELINE_RUBRIC,
        proposer=proposer,
        evaluator=evaluator,
        costs=_COSTS,
        brier_floor=0.0,
        private_values={},
        n_rounds=2,
        baseline_train=baseline,
        round_offset=3,
    )

    assert [r.round_num for r in rounds] == [4, 5]


def test_run_rounds_prefers_shorter_text_on_a_tie_and_calls_on_round() -> None:
    pairs = [rr.UsablePair("p1", "oa1", "ob1", "A1", "B1", "a")]
    baseline_cases = [_pair_cases(pair_id="p1", expected="a", prediction="a", sure=True)]
    proposer = FakeProposer(
        [rr.RubricProposal(theory="t", expected_effect="e", definition="short")]
    )
    evaluator = FakeEvaluator([_eval_result(baseline_cases)])
    seen: list[int] = []

    rounds = rr.run_rounds(
        propose_pairs=pairs,
        held_pairs=pairs,
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
        costs=_COSTS,
        brier_floor=0.0,
        private_values={},
        n_rounds=1,
        on_round=lambda round_result: seen.append(round_result.round_num),
    )

    assert rounds[0].accepted is True
    assert seen == [1]


# ---------------------------------------------------------------------------
# Scoring: net value, Brier, acceptance
# ---------------------------------------------------------------------------


def test_commit_costs_read_each_threshold_as_its_break_even_precision() -> None:
    """The regression: an inverted ratio ((1-t)/t) makes a wrong auto-commit cheaper
    than a right one is valuable, so the loop would reward confident guessing."""
    costs = rr.CommitCosts.from_thresholds(winner_commit_threshold=0.75, tie_commit_threshold=0.85)
    assert costs.k_winner == pytest.approx(3.0)
    assert costs.k_tie == pytest.approx(0.85 / 0.15)


def test_net_charges_each_wrong_commit_its_own_cost_and_ignores_unsure() -> None:
    """The regression: charging every wrong commit the same k, or counting unsure
    cases, which cost the operator a look whether Jev was right or not."""
    cases = [
        _pair_cases(pair_id="rs", expected="a", prediction="a", sure=True),
        _pair_cases(pair_id="ws-winner", expected="tie", prediction="a", sure=True),
        _pair_cases(pair_id="ws-tie", expected="a", prediction="tie", sure=True),
        _pair_cases(pair_id="ru", expected="b", prediction="b", sure=False),
        _pair_cases(pair_id="wu", expected="b", prediction="a", sure=False),
    ]
    assert _COSTS.net(cases) == pytest.approx(1 - 3.0 - 5.0)


def test_brier_scores_the_three_way_distribution_against_the_ruling() -> None:
    """The regression: mis-splitting P(clear winner) into a/b, so a confident call on
    the right side scores like a wrong one."""
    certain_a = _pair_cases(
        pair_id="p", expected="a", prediction="a", sure=True, p_clear=1.0, p_a=1.0
    )
    certain_tie = _pair_cases(
        pair_id="p", expected="a", prediction="tie", sure=True, p_clear=0.0, p_a=0.5
    )
    split = _pair_cases(
        pair_id="p", expected="b", prediction="b", sure=False, p_clear=0.8, p_a=0.25
    )

    assert certain_a.brier == 0.0
    assert certain_tie.brier == pytest.approx(2.0)
    assert split.p_ruling == pytest.approx(0.6)
    assert split.brier == pytest.approx(0.2**2 + 0.4**2 + 0.2**2)


def test_brier_noise_floor_is_two_standard_errors_of_the_paired_difference() -> None:
    first = _eval_result(
        [
            _pair_cases(
                pair_id="p1", expected="a", prediction="a", sure=True, p_clear=1.0, p_a=1.0
            ),
            _pair_cases(
                pair_id="p2", expected="a", prediction="a", sure=True, p_clear=1.0, p_a=1.0
            ),
        ]
    )
    second = _eval_result(
        [
            _pair_cases(
                pair_id="p1", expected="a", prediction="a", sure=True, p_clear=1.0, p_a=0.9
            ),
            _pair_cases(
                pair_id="p2", expected="a", prediction="a", sure=True, p_clear=1.0, p_a=1.0
            ),
        ]
    )
    diffs = [0.0 - 2 * 0.1**2, 0.0]
    expected = 2 * statistics.stdev(diffs) / math.sqrt(2)

    assert rr.brier_noise_floor(first, second) == pytest.approx(expected)
    assert rr.brier_noise_floor(first, first) == 0.0
    single = _eval_result([first.cases[0]])
    assert rr.brier_noise_floor(single, single) == 0.0


def test_accepts_orders_net_then_brier_beyond_the_floor_then_brevity() -> None:
    """The regressions: Brier outvoting net, jitter inside the floor counting as a
    win, and a longer text winning a true tie."""

    def accepts(
        candidate: rr.Score, current: rr.Score, cand_text: str = "x", curr_text: str = "xx"
    ) -> bool:
        return rr.accepts(
            candidate, current, brier_floor=0.01, candidate_text=cand_text, current_text=curr_text
        )

    # 1. Net is supreme (net=1 always beats net=0, regardless of Brier or length)
    assert accepts(rr.Score(net=1, brier=0.9), rr.Score(net=0, brier=0.1), cand_text="x" * 1000)
    assert not accepts(rr.Score(net=0, brier=0.1), rr.Score(net=1, brier=0.9), cand_text="x")

    # 2. When net is tied, brevity and Brier trade off (100 chars = 0.01 brier).
    # Baseline brier=0.32 vs 0.30 (candidate is 0.02 worse).
    # If candidate is 400 chars shorter, length_gain = +400 -> +0.04 to adjusted brier gain.
    # Total adjusted gain = -0.02 + 0.04 = +0.02.
    # +0.02 > 0.01 (noise floor), so it wins!
    assert accepts(
        rr.Score(net=0, brier=0.32), rr.Score(net=0, brier=0.30), cand_text="x", curr_text="x" * 401
    )

    # If candidate is 200 chars longer (-0.02 gain) and Brier is 0.05 better (+0.05).
    # Total adjusted gain = 0.05 - 0.02 = 0.03. > 0.01 floor. Wins!
    assert accepts(
        rr.Score(net=0, brier=0.25), rr.Score(net=0, brier=0.30), cand_text="x" * 201, curr_text="x"
    )

    # Inside the noise floor, it returns False if it's not strictly better
    assert not accepts(
        rr.Score(net=0, brier=0.32),
        rr.Score(net=0, brier=0.30),
        cand_text="x" * 200,
        curr_text="x" * 200,
    )


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


def test_privacy_gate_rejects_candidate_carrying_the_configured_baseline() -> None:
    with pytest.raises(rr.PrivacyViolationError, match="SCREEN_COMPENSATION_BASELINE"):
        rr.validate_candidate(
            "Anchors: below $1,234,567 is Poor; above is Strong.",
            {"SCREEN_COMPENSATION_BASELINE": "$1,234,567"},
        )


def test_candidate_that_drops_a_placeholder_is_rejected() -> None:
    """The regression: a proposer that rewrites the baseline placeholder as a literal
    number gets that number written into the public rubric.yaml."""
    with pytest.raises(rr.PlaceholderDroppedError, match="SCREEN_COMPENSATION_BASELINE"):
        rr.require_placeholders_kept(
            "Above SCREEN_COMPENSATION_BASELINE is Strong.", "Above $1 is Strong."
        )


def test_candidate_that_keeps_its_placeholder_is_accepted() -> None:
    rr.require_placeholders_kept(
        "Above SCREEN_COMPENSATION_BASELINE is Strong.",
        "Clearly above SCREEN_COMPENSATION_BASELINE is Strong.",
    )


def test_privacy_gate_accepts_clean_candidate() -> None:
    rr.validate_candidate(
        """fit_anchors:
  Poor: Relocation required.
  Mixed: Remote offered but team is centrally based.
  Strong: Distributed-first company.
""",
        {"SCREEN_COMPENSATION_BASELINE": "$1,234,567"},
    )


def test_proposer_injects_private_values_when_present_in_rubric() -> None:
    class SpyClient:
        def __init__(self):
            self.last_kwargs = {}

        def ProposeRubricEdit(self, **kwargs):
            self.last_kwargs = kwargs
            return type(
                "Obj",
                (),
                {
                    "theory": "theory",
                    "expected_effect": "effect",
                    "definition": "def",
                    "fit_anchor_poor": "poor",
                    "fit_anchor_mixed": "mixed",
                    "fit_anchor_strong": "strong",
                    "look_for": "look",
                },
            )()

    spy = SpyClient()
    proposer = cli.AnthropicProposer(
        costs=rr.CommitCosts.from_thresholds(
            winner_commit_threshold=0.75, tie_commit_threshold=0.85
        ),
        private_values={"SCREEN_COMPENSATION_BASELINE": "$125k"},
        brier_floor=0.01,
        context_mode="sampled",
        client=spy,
    )

    # 1. No placeholder in text -> private_values_text is None
    rubric_without = "### Compensation (slug: compensation, weight: 2)\ndefinition: No placeholder."
    proposer.propose(current_rubric_text=rubric_without, labeled_cases=[], prior_rounds=[])
    assert spy.last_kwargs["private_values_text"] is None

    # 2. Placeholder in text -> private_values_text has the value
    rubric_with = "### Compensation (slug: compensation, weight: 2)\ndefinition: Has SCREEN_COMPENSATION_BASELINE."
    proposer.propose(current_rubric_text=rubric_with, labeled_cases=[], prior_rounds=[])
    assert "SCREEN_COMPENSATION_BASELINE: $125k" in spy.last_kwargs["private_values_text"]
