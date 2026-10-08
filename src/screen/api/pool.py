"""The one place that reads the DB to assemble a scored screening pool - both the JSON
and HTML routers call `rank_screening_pool` rather than each re-deriving
`comparisons_by_target`/`companies_by_opening` from stored rows.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import numpy as np

from screen.api.scoring import latest_ruling_by_assertion, pool_for_screening
from screen.extract.prompt import rubric_text_for_dimension
from screen.score.compare import Comparison as ScoreComparison
from screen.score.compare_picker import ComparisonSuggestion, select_comparison
from screen.score.compare_probability import pre_comparison_probability
from screen.score.rubric_gate import rubric_similarity_verdict
from screen.score.scorer import stats_for_target
from screen.score.types import PoolScoreResult, ScoringConfig
from screen.store.db import connect
from screen.store.repo import (
    append_comparison,
    assertion_rulings_for_opening,
    assertions_for_opening,
    comparisons_for_target,
    get_dimension_digest,
    list_openings,
)
from screen.types import Assertion, ComparisonOutcome, Fit, Opening, Target
from screen.types import Comparison as StoredComparison
from screen.verdict.few_shot import few_shot_examples_from_rulings
from screen.verdict.protocol import FewShotExample, RubricVerdict, VerdictProvider

# Safety bound on confident auto-ties per `/compare` request — not a tuned behavior
# knob, just a guard against an unbounded chain if the entire remaining pool happens to
# be confidently Jev-ruled.
_MAX_SHORT_CIRCUIT_ITERATIONS = 20


def _to_score_comparison(comparison: StoredComparison) -> ScoreComparison:
    """Map a stored `screen.types.Comparison` (opening_a/opening_b/outcome) onto the pure
    fit's `winner`/`loser`/`tie` shape — the fit only ever needs the resolved judgment, and
    `provenance` rides along so the fit can pick this comparison's beta."""
    if comparison.outcome == "tie":
        return ScoreComparison(
            winner=comparison.opening_a_id,
            loser=comparison.opening_b_id,
            tie=True,
            provenance=comparison.provenance,
        )
    if comparison.outcome == "a":
        return ScoreComparison(
            winner=comparison.opening_a_id,
            loser=comparison.opening_b_id,
            provenance=comparison.provenance,
        )
    return ScoreComparison(
        winner=comparison.opening_b_id,
        loser=comparison.opening_a_id,
        provenance=comparison.provenance,
    )


def _screening_pool_inputs(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    openings: list[Opening] | None = None,
) -> tuple[
    list[Opening],
    dict[str, list[Assertion]],
    dict[str, dict[str, Fit]],
    dict[str, list[ScoreComparison]],
    dict[str, str],
]:
    """Collect the raw inputs the pool scorer and comparison picker both need."""
    openings = openings if openings is not None else list_openings(conn, stage="screening")
    assertions_by_opening = {o.id: assertions_for_opening(conn, o.id) for o in openings}
    rulings_by_opening: dict[str, dict[str, Fit]] = {
        o.id: {
            ruling.assertion_id: ruling.fit
            for ruling in latest_ruling_by_assertion(
                assertion_rulings_for_opening(conn, o.id)
            ).values()
        }
        for o in openings
    }
    comparisons_by_target = {
        target: [_to_score_comparison(c) for c in comparisons_for_target(conn, target)]
        for target in config.dimension_weights
    }
    companies_by_opening = {o.id: o.company_id for o in openings}
    return (
        openings,
        assertions_by_opening,
        rulings_by_opening,
        comparisons_by_target,
        companies_by_opening,
    )


def rank_screening_pool(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    openings: list[Opening] | None = None,
) -> PoolScoreResult:
    """All screening openings scored jointly with their assertion-level rulings and any
    stored comparisons — every dimension with a comparison or a same-company pair gets
    a comparison-fitted posterior instead of its ordinary assertion-derived prior.
    `openings` defaults to the live screening stage; a caller that needs one opening
    included regardless of its stage (the single-opening score route) passes its own
    union."""
    (
        openings,
        assertions_by_opening,
        rulings_by_opening,
        comparisons_by_target,
        companies_by_opening,
    ) = _screening_pool_inputs(conn, config, openings=openings)
    return pool_for_screening(
        openings,
        assertions_by_opening,
        rulings_by_opening,
        config,
        comparisons_by_target=comparisons_by_target,
        companies_by_opening=companies_by_opening,
    )


def _outcome_for_pair(
    comparison: ScoreComparison, opening_a_id: str, opening_b_id: str
) -> ComparisonOutcome:
    """Maps the gate's winner/loser/tie result back onto the caller's (a, b) order."""
    if comparison.tie:
        return "tie"
    return "a" if comparison.winner == opening_a_id else "b"


def _few_shot_examples_for_target(
    conn: sqlite3.Connection,
    target: str,
    *,
    rng: np.random.Generator,
    max_examples: int,
) -> list[FewShotExample]:
    """Samples few-shot examples from the operator's own past rulings on this dimension
    — the rubric nuance the rubric text alone doesn't capture."""
    rulings = [c for c in comparisons_for_target(conn, target) if c.provenance == "operator"]
    opening_ids = {oid for c in rulings for oid in (c.opening_a_id, c.opening_b_id)}
    digests_by_opening: dict[str, str] = {}
    for opening_id in opening_ids:
        digest = get_dimension_digest(conn, opening_id, target)
        if digest is not None:
            digests_by_opening[opening_id] = digest.digest
    return few_shot_examples_from_rulings(
        rulings, digests_by_opening, rng=rng, max_examples=max_examples
    )


def _consult_jev_for_suggestion(
    conn: sqlite3.Connection,
    suggestion: ComparisonSuggestion,
    assertions_by_opening: dict[str, list[Assertion]],
    rulings_by_opening: dict[str, dict[str, Fit]],
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    rng: np.random.Generator,
) -> tuple[StoredComparison | None, RubricVerdict | None]:
    """Jev's live short-circuit for one suggested pair: the operator-suggested pair goes
    straight to Jev's confidence gate, every time — Jev is cheap enough that there's no
    pair to pre-filter it away from, and a cosine pre-filter on digest *text* was
    rejecting exactly the rubric-similar-but-differently-worded pairs Jev exists to catch
    (measured against the live pool: scouting F-SC3). Returns `(None, None)` when there's
    no cached digest — Jev was never consulted, nothing to show. Returns
    `(None, verdict)` when Jev was consulted but wasn't confident — `verdict` is Jev's
    raw read, carried so the operator can see what Jev said on a pair it couldn't settle
    rather than it looking like Jev was silent."""
    digest_a = get_dimension_digest(conn, suggestion.opening_a_id, suggestion.target)
    digest_b = get_dimension_digest(conn, suggestion.opening_b_id, suggestion.target)
    if digest_a is None or digest_b is None:
        return None, None
    few_shot_examples = _few_shot_examples_for_target(
        conn, suggestion.target, rng=rng, max_examples=config.jev_few_shot_examples
    )
    gate = rubric_similarity_verdict(
        suggestion.opening_a_id,
        suggestion.opening_b_id,
        rubric_text=rubric_text_for_dimension(suggestion.target),
        digest_a=digest_a.digest,
        digest_b=digest_b.digest,
        few_shot_examples=few_shot_examples,
        provider=verdict_provider,
        confidence_threshold=config.jev_confidence_threshold,
    )
    if gate.comparison is None:
        return None, gate.verdict
    stats_a = stats_for_target(
        assertions_by_opening[suggestion.opening_a_id],
        config,
        suggestion.target,
        rulings_by_opening.get(suggestion.opening_a_id) or None,
    )
    stats_b = stats_for_target(
        assertions_by_opening[suggestion.opening_b_id],
        config,
        suggestion.target,
        rulings_by_opening.get(suggestion.opening_b_id) or None,
    )
    predicted_a_beats_b = pre_comparison_probability(
        stats_a.mean, stats_a.half_width, stats_b.mean, stats_b.half_width
    )
    stored = StoredComparison(
        id=str(uuid4()),
        opening_a_id=suggestion.opening_a_id,
        opening_b_id=suggestion.opening_b_id,
        target=cast("Target", suggestion.target),
        outcome=_outcome_for_pair(
            gate.comparison, suggestion.opening_a_id, suggestion.opening_b_id
        ),
        provenance="provisional",
        predicted_a_beats_b=predicted_a_beats_b,
        created_at=datetime.now(UTC),
    )
    return stored, gate.verdict


@dataclass
class CompareProgress:
    """Live status for the comparison pre-screen pass — the polling web route's view
    into what Jev has ruled so far. `ruled` grows in place as each confident verdict
    lands, so a concurrent poll sees partial progress; mirrors `BatchEngine`'s
    `MutableMapping` progress dict, but typed since this progress has one shape, not a
    research batch's. `final_suggestion` is the pair/dimension Jev could not settle —
    what the operator sees once the pass ends, `None` if the pool had nothing left to
    suggest at all. `final_suggestion_jev_read` is Jev's raw verdict on that exact pair,
    when Jev was consulted but wasn't confident — `None` both when there's no
    `final_suggestion` and when Jev was never consulted at all (no cached digest), so a
    caller must check `final_suggestion` is set before treating `None` here as
    meaningful. `completed` disambiguates `final_suggestion is None` from "hasn't run
    yet": the route only reruns the pass when `completed` is still `False`."""

    running: bool = False
    completed: bool = False
    ruled: list[StoredComparison] = field(default_factory=list)
    final_suggestion: ComparisonSuggestion | None = None
    final_suggestion_jev_read: RubricVerdict | None = None


def run_prescreen(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    progress: CompareProgress,
    max_iterations: int = _MAX_SHORT_CIRCUIT_ITERATIONS,
) -> None:
    """Rules every confidently-gated (pair, dimension) ahead of the operator's first
    `/compare` view this pass, persisting each one and appending it to `progress.ruled`
    as it lands — the polling route renders this list live. Stops at the first
    suggestion Jev isn't confident about, when nothing is left to suggest, or at
    `max_iterations` (a safety bound, not a tuned behavior knob)."""
    progress.running = True
    rng = np.random.default_rng(config.seed)
    try:
        for _ in range(max_iterations):
            (
                openings,
                assertions_by_opening,
                rulings_by_opening,
                comparisons_by_target,
                companies_by_opening,
            ) = _screening_pool_inputs(conn, config)
            pool_result = rank_screening_pool(conn, config, openings=openings)
            p_top_k_by_opening = {r.opening_id: r.p_top_k for r in pool_result.opening_ranks}
            suggestion = select_comparison(
                [o.id for o in openings],
                companies_by_opening,
                assertions_by_opening,
                comparisons_by_target,
                p_top_k_by_opening,
                config=config,
                rulings_by_opening=rulings_by_opening,
                rng=rng,
            )
            if suggestion is None:
                return

            comparison, jev_read = _consult_jev_for_suggestion(
                conn,
                suggestion,
                assertions_by_opening,
                rulings_by_opening,
                config,
                verdict_provider=verdict_provider,
                rng=rng,
            )
            if comparison is None:
                progress.final_suggestion = suggestion
                progress.final_suggestion_jev_read = jev_read
                return
            append_comparison(conn, comparison)
            progress.ruled.append(comparison)
    finally:
        progress.running = False
        progress.completed = True


def run_prescreen_in_background(
    db_path: Path,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    progress: CompareProgress,
) -> None:
    """`run_prescreen` entry point for `fastapi.BackgroundTasks`: opens its own
    connection, since the request that scheduled this has already returned (mirrors
    `BatchEngine.run`)."""
    conn = connect(db_path)
    try:
        run_prescreen(conn, config, verdict_provider=verdict_provider, progress=progress)
    finally:
        conn.close()
