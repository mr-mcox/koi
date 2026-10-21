"""Tests for `screen.recalibration` — the autoresearch loop.

Covers: eligibility gate, propose/held-out split, round sequencing,
no-improvement reporting, and privacy gate on candidate text.
The LLM proposer is injected via a Protocol so no live calls are made.
"""

from __future__ import annotations

import sqlite3
import textwrap

import pytest

from screen import recalibration as rr
from scripts import recalibrate_rubric as cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ClosingConnection(sqlite3.Connection):
    def __del__(self) -> None:  # pragma: no cover - safety net for test cleanup
        try:
            self.close()
        except Exception:
            pass


def test_open_db_accepts_an_explicit_db_path(tmp_path) -> None:
    db_path = tmp_path / "screen.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE dimension_digests (
            id TEXT PRIMARY KEY,
            opening_id TEXT NOT NULL,
            target TEXT NOT NULL,
            digest TEXT NOT NULL,
            assertion_count INTEGER NOT NULL,
            computed_at TEXT NOT NULL
        );
        """)
    conn.commit()
    conn.close()

    opened = cli._open_db(db_path)
    opened.close()


def _make_conn() -> sqlite3.Connection:
    """In-memory DB with the tables the script reads."""
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
) -> None:
    oid_a = f"{pair_id}_a"
    oid_b = f"{pair_id}_b"
    conn.execute(
        """INSERT INTO comparisons VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
    for oid, label in [(oid_a, "digest-a"), (oid_b, "digest-b")]:
        conn.execute(
            """INSERT INTO dimension_digests VALUES (?,?,?,?,?,?)""",
            (f"{oid}-{target}", oid, target, f"{label} for {pair_id}", 1, "2026-01-01T00:00:00"),
        )
    conn.commit()


def _labeled_cases(pairs: list[rr.UsablePair]) -> list[rr.LabeledCase]:
    return [
        rr.LabeledCase(
            digest_a=p.digest_a,
            digest_b=p.digest_b,
            expected=p.expected,
            jev_prediction="tie",
            jev_confidence=0.5,
        )
        for p in pairs
    ]


# ---------------------------------------------------------------------------
# Fake proposer
# ---------------------------------------------------------------------------


class FakeProposer:
    """Returns canned rubric text proposals in order, repeating the last."""

    def __init__(self, proposals: list[str]) -> None:
        assert proposals, "FakeProposer requires at least one proposal"
        self._proposals = proposals
        self._index = 0
        self.calls: list[dict] = []

    def propose(
        self,
        *,
        current_rubric_text: str,
        labeled_cases: list[rr.LabeledCase],
        prior_rounds: list[rr.RoundResult],
    ) -> str:
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


# ---------------------------------------------------------------------------
# Fake evaluator (order-averaged bucket counts without real Jev calls)
# ---------------------------------------------------------------------------


class FakeEvaluator:
    """Returns canned BucketCounts per call, repeating the last."""

    def __init__(self, results: list[rr.BucketCounts]) -> None:
        assert results
        self._results = results
        self._index = 0

    def evaluate(
        self,
        pairs: list[rr.UsablePair],
        rubric_text: str,
    ) -> rr.BucketCounts:
        result = self._results[min(self._index, len(self._results) - 1)]
        self._index += 1
        return result


# ---------------------------------------------------------------------------
# Eligibility gate
# ---------------------------------------------------------------------------


def test_eligibility_gate_rejects_target_below_floor() -> None:
    """load_pairs returns empty and a shortfall when n < floor."""
    conn = _make_conn()
    for i in range(5):
        _insert_pair(conn, pair_id=f"p{i}", target="trajectory")

    pairs, shortfall = rr.load_pairs(conn, target="trajectory", floor=70)
    assert pairs == []
    assert shortfall == 65  # 70 - 5
    conn.close()


def test_eligibility_gate_accepts_target_at_floor() -> None:
    conn = _make_conn()
    for i in range(70):
        _insert_pair(conn, pair_id=f"p{i}", target="location")

    pairs, shortfall = rr.load_pairs(conn, target="location", floor=70)
    assert len(pairs) == 70
    assert shortfall == 0
    conn.close()


def test_eligibility_gate_skips_non_operator_comparisons() -> None:
    conn = _make_conn()
    for i in range(70):
        _insert_pair(conn, pair_id=f"p{i}", target="location", provenance="operator")
    for i in range(10):
        _insert_pair(conn, pair_id=f"prov{i}", target="location", provenance="provisional")

    pairs, shortfall = rr.load_pairs(conn, target="location", floor=70)
    assert len(pairs) == 70  # provisional not counted
    conn.close()


def test_eligibility_gate_skips_pairs_missing_digest() -> None:
    conn = _make_conn()
    for i in range(72):
        _insert_pair(conn, pair_id=f"p{i}", target="location")
    # Break digests for two pairs
    conn.execute("DELETE FROM dimension_digests WHERE opening_id = 'p0_a'")
    conn.execute("DELETE FROM dimension_digests WHERE opening_id = 'p1_b'")
    conn.commit()

    pairs, shortfall = rr.load_pairs(conn, target="location", floor=70)
    assert len(pairs) == 70

    # ---------------------------------------------------------------------------
    # Propose / held-out split
    # ---------------------------------------------------------------------------
    conn.close()


def test_split_is_deterministic_with_same_seed() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")
    pairs, _ = rr.load_pairs(conn, target="location", floor=70)

    propose_a, held_a = rr.split_pairs(pairs, seed=42)
    propose_b, held_b = rr.split_pairs(pairs, seed=42)
    assert [p.pair_id for p in propose_a] == [p.pair_id for p in propose_b]
    assert [p.pair_id for p in held_a] == [p.pair_id for p in held_b]
    conn.close()


def test_split_is_different_with_different_seed() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")
    pairs, _ = rr.load_pairs(conn, target="location", floor=70)

    propose_a, _ = rr.split_pairs(pairs, seed=1)
    propose_b, _ = rr.split_pairs(pairs, seed=2)
    assert [p.pair_id for p in propose_a] != [p.pair_id for p in propose_b]
    conn.close()


def test_split_sizes_are_reasonable() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")
    pairs, _ = rr.load_pairs(conn, target="location", floor=70)

    propose, held = rr.split_pairs(pairs, seed=42)
    assert len(propose) + len(held) == len(pairs)
    assert len(held) >= 15  # enough to measure something

    # ---------------------------------------------------------------------------
    # Round sequencing: prior rounds visible in subsequent proposer calls
    # ---------------------------------------------------------------------------
    conn.close()


def test_round_2_prompt_contains_round_1_result() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")

    pairs, _ = rr.load_pairs(conn, target="location", floor=70)
    propose_pairs, held_pairs = rr.split_pairs(pairs, seed=42)

    baseline = rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12)
    worse = rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12)
    better = rr.BucketCounts(right_sure=8, right_unsure=10, wrong_sure=1, wrong_unsure=11)

    proposer = FakeProposer(["rubric text v1", "rubric text v2"])
    evaluator = FakeEvaluator([baseline, worse, better])

    rounds = rr.run_rounds(
        propose_pairs=propose_pairs,
        held_pairs=held_pairs,
        labeled_cases=_labeled_cases(propose_pairs),
        current_rubric_text="original rubric",
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=2,
    )

    assert len(rounds) == 2
    # Round 2's proposer call saw round 1's result
    assert len(proposer.calls[1]["prior_rounds"]) == 1
    assert proposer.calls[1]["prior_rounds"][0] is rounds[0]

    # ---------------------------------------------------------------------------
    # No-improvement: best candidate is "no edit" when nothing beats baseline
    # ---------------------------------------------------------------------------
    conn.close()


def test_no_improvement_returns_none_candidate() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")

    pairs, _ = rr.load_pairs(conn, target="location", floor=70)
    propose_pairs, held_pairs = rr.split_pairs(pairs, seed=42)

    baseline = rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12)
    same = rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12)

    proposer = FakeProposer(["original rubric"])
    evaluator = FakeEvaluator([baseline, same])

    rounds = rr.run_rounds(
        propose_pairs=propose_pairs,
        held_pairs=held_pairs,
        labeled_cases=_labeled_cases(propose_pairs),
        current_rubric_text="original rubric",
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=1,
    )

    best = rr.best_round(rounds, baseline, "original rubric")
    assert best is None  # no candidate beat baseline
    conn.close()


def test_run_rounds_accepts_precomputed_baseline_train() -> None:
    conn = _make_conn()
    for i in range(80):
        _insert_pair(conn, pair_id=f"p{i}", target="location")

    pairs, _ = rr.load_pairs(conn, target="location", floor=70)
    propose_pairs, held_pairs = rr.split_pairs(pairs, seed=42)

    baseline_train = rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12)
    proposer = FakeProposer(["original rubric"])
    evaluator = FakeEvaluator(
        [
            rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12),
            rr.BucketCounts(right_sure=5, right_unsure=10, wrong_sure=3, wrong_unsure=12),
        ]
    )

    rounds = rr.run_rounds(
        propose_pairs=propose_pairs,
        held_pairs=held_pairs,
        labeled_cases=_labeled_cases(propose_pairs),
        current_rubric_text="original rubric",
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=1,
        baseline_train=baseline_train,
    )

    assert len(rounds) == 1
    conn.close()


def test_objective_prioritizes_more_right_then_more_confident_right_then_less_wrong_then_shorter() -> (
    None
):
    a = rr.BucketCounts(right_sure=3, right_unsure=4, wrong_sure=2, wrong_unsure=1)
    b = rr.BucketCounts(right_sure=4, right_unsure=3, wrong_sure=1, wrong_unsure=2)
    assert rr.objective(b, "short text") > rr.objective(a, "much longer text")


def test_objective_prefers_fewer_confident_wrong_when_right_is_tied() -> None:
    a = rr.BucketCounts(right_sure=4, right_unsure=4, wrong_sure=3, wrong_unsure=0)
    b = rr.BucketCounts(right_sure=4, right_unsure=4, wrong_sure=1, wrong_unsure=2)
    assert rr.objective(b, "same length") > rr.objective(a, "same length")


def test_objective_uses_length_only_after_bucket_tie() -> None:
    a = rr.BucketCounts(right_sure=4, right_unsure=4, wrong_sure=1, wrong_unsure=2)
    b = rr.BucketCounts(right_sure=4, right_unsure=4, wrong_sure=1, wrong_unsure=2)
    assert rr.objective(b, "short") > rr.objective(a, "a much longer rubric text")


def test_parse_dimension_candidate_round_trips_location_fields() -> None:
    definition, fit_anchors, look_for = cli._parse_dimension_candidate(
        """### Location compatibility (slug: location, weight: 6)
Whether the role's location arrangement is workable and desirable for the
operator's actual situation. Ordered: remote-first company > remote as
an option > hybrid or awkward remote > relocation required. Negotiability
shows up as spread within a Fit band via the ordinary shrinkage math.
Fit anchors:
  Poor: Relocation required, stated, with no flexibility language; or a
    commute/schedule the operator's situation cannot accommodate.
  Mixed: Remote is offered but the posting is silent on travel or team
    distribution culture; or the company is centrally based and hiring
    this seat remotely as an exception; or hybrid with mandated in-office
    days that create a genuine commute/schedule burden.
  Strong: A genuinely distributed / remote-first company, or a remote role that
    openly acknowledges only occasional travel as the tradeoff.
Look for: Explicit location/remote policy language; whether the team/company is
    distributed by design or centrally based; travel expectations; whether
    remote hires exist at the level being applied for; metro/commute distance
    from the operator's home base; any relocation assistance or flexibility
    language."""
    )
    assert "workable and desirable" in definition
    assert set(fit_anchors) == {"Poor", "Mixed", "Strong"}
    assert "Explicit location/remote policy language" in look_for


def test_bucket_counts_formatting_and_best_round_pick() -> None:
    counts = rr.BucketCounts(right_sure=3, right_unsure=4, wrong_sure=1, wrong_unsure=2)
    assert counts.total == 10
    assert counts.precision_when_sure == 3 / 4
    assert "precision-when-sure" in str(counts)

    baseline = rr.BucketCounts(right_sure=1, right_unsure=0, wrong_sure=0, wrong_unsure=0)
    rounds = [
        rr.RoundResult(
            1, "a", rr.BucketCounts(right_sure=1), "t1", train_buckets=rr.BucketCounts(right_sure=1)
        ),
        rr.RoundResult(
            2, "b", rr.BucketCounts(right_sure=4), "t2", train_buckets=rr.BucketCounts(right_sure=4)
        ),
    ]
    winner = rr.best_round(rounds, baseline, "baseline rubric")
    assert winner is not None
    assert winner.round_num == 2


# ---------------------------------------------------------------------------
# Privacy gate: candidate containing salary figure must be rejected
# ---------------------------------------------------------------------------


def test_privacy_gate_rejects_candidate_with_salary_figure() -> None:
    """A candidate rubric containing a known private pattern raises."""
    bad_text = "Anchors: below $230,000 is Poor; above is Strong."
    with pytest.raises(rr.PrivacyViolationError, match="230"):
        rr.validate_candidate(bad_text)


def test_privacy_gate_accepts_clean_candidate() -> None:
    clean_text = textwrap.dedent("""\
        fit_anchors:
          Poor: "Relocation required."
          Mixed: "Remote offered but team is centrally based."
          Strong: "Distributed-first company."
    """)
    rr.validate_candidate(clean_text)  # must not raise
