"""The comparison pre-screen engine: picks the next pair to judge, consults Jev for a
provisional ruling, and runs ahead of the operator in the background.

It reads the pool through `screen.pool` rather than assembling one of its own.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import numpy as np

from screen.compare.picker import ComparisonSuggestion, select_comparison
from screen.compare.probability import pre_comparison_probability
from screen.compare.rubric_gate import rubric_similarity_verdict
from screen.extract.prompt import RubricText
from screen.pool import rank_screening_pool, screening_pool_inputs
from screen.score.pairwise import Comparison as ScoreComparison
from screen.score.scorer import stats_for_target
from screen.score.types import ScoringConfig
from screen.store.db import connect
from screen.store.repo import (
    append_comparison,
    comparisons_for_target,
    get_dimension_digest,
)
from screen.types import Assertion, ComparisonOutcome, Fit, Target
from screen.types import Comparison as StoredComparison
from screen.verdict.few_shot import few_shot_examples_from_rulings
from screen.verdict.protocol import FewShotExample, RubricVerdict, VerdictProvider

# Safety bound on confident auto-ties per `/compare` request — not a tuned behavior
# knob, just a guard against an unbounded chain if the entire remaining pool happens to
# be confidently Jev-ruled.
_MAX_SHORT_CIRCUIT_ITERATIONS = 20
# Throughput instrumentation for the pre-screen pass: paired with `screen.compare` in
# the web routes, these lines say where a live session's wall-clock time actually went.
_prescreen_log = logging.getLogger("screen.prescreen")


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
    rubric: RubricText,
    rng: np.random.Generator,
) -> tuple[StoredComparison | None, RubricVerdict | None]:
    """Jev's live short-circuit for one suggested pair: the operator-suggested pair goes
    straight to Jev's confidence gate, every time, with no pre-filter. Similarity of
    digest *text* is not similarity under the rubric: rubric-similar but differently
    worded pairs are exactly the ones Jev exists to catch (scouting F-SC3). Returns `(None, None)` when there's
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
        rubric_text=rubric.for_dimension(suggestion.target),
        digest_a=digest_a.digest,
        digest_b=digest_b.digest,
        few_shot_examples=few_shot_examples,
        provider=verdict_provider,
        confidence_threshold=config.jev_confidence_threshold,
        rng=rng,
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
        opening_a_digest_version=digest_a.id,
        opening_b_digest_version=digest_b.id,
        created_at=datetime.now(UTC),
    )
    return stored, gate.verdict


@dataclass
class CompareState:
    """Monotonic compare-write state for the in-process cache: `version` bumps every time
    a comparison row is appended, and `last_write` records the unordered pair + target of
    the most recent write so a stale-by-one cached suggestion can still be rejected when it
    is literally the pair just judged."""

    version: int = 0
    last_write: tuple[frozenset[str], str] | None = None


@dataclass
class CompareCache:
    """The last compare suggestion a background prescreen produced. `version` is the
    compare-write version the suggestion was computed against; callers may reuse it for the
    current version or one write behind if the pair is still legal.

    `speculative` is the suggestion computed *while the operator was still deciding* the
    one in `suggestion`, with that triple excluded. It is deliberately one state behind by
    construction — it does not know the outcome the operator chose — which is the
    stale-by-one trade the whole cache rests on. On a write it is promoted into
    `suggestion` so the next page can render without waiting for a fresh pool score."""

    version: int = -1
    suggestion: ComparisonSuggestion | None = None
    jev_read: RubricVerdict | None = None
    speculative: ComparisonSuggestion | None = None
    speculative_jev_read: RubricVerdict | None = None
    speculative_for: tuple[frozenset[str], str] | None = None


@dataclass
class CompareProgress:
    """Live status for the comparison pre-screen pass — the polling web route's view
    into what Jev has ruled so far. `ruled` grows in place as each confident verdict
    lands, so a concurrent poll sees partial progress. `version` is the compare-write
    version this run is based on. `final_suggestion*` is the suggestion the run left
    unresolved, the same one it published to the cache."""

    running: bool = False
    completed: bool = False
    version: int | None = None
    ruled: list[StoredComparison] = field(default_factory=list)
    final_suggestion: ComparisonSuggestion | None = None
    final_suggestion_jev_read: RubricVerdict | None = None


def comparison_key(opening_a_id: str, opening_b_id: str, target: str) -> tuple[frozenset[str], str]:
    return frozenset({opening_a_id, opening_b_id}), target


def _cache_operator_suggestion(
    compare_cache: CompareCache,
    progress: CompareProgress,
    *,
    version: int,
    suggestion: ComparisonSuggestion | None,
    jev_read: RubricVerdict | None,
) -> None:
    """Publish what the operator should see next. The cache and the progress object hold
    the same answer: the cache survives this pass for the next request to reuse, the
    progress object is what the in-flight polling page resolves to."""
    compare_cache.version = version
    compare_cache.suggestion = suggestion
    compare_cache.jev_read = jev_read
    compare_cache.speculative = None
    compare_cache.speculative_jev_read = None
    compare_cache.speculative_for = None
    progress.final_suggestion = suggestion
    progress.final_suggestion_jev_read = jev_read


def _cache_speculative_suggestion(
    compare_cache: CompareCache,
    *,
    excluded: tuple[frozenset[str], str],
    version: int,
    suggestion: ComparisonSuggestion | None,
    jev_read: RubricVerdict | None,
) -> None:
    """Publish the speculative next comparison without touching the on-screen one."""
    compare_cache.version = version
    compare_cache.speculative = suggestion
    compare_cache.speculative_jev_read = jev_read
    compare_cache.speculative_for = excluded


# What one prescreen step did: appended a comparison, found the version moved under its Jev
# consult (nothing written), or stopped with nothing left to auto-rule.
_StepOutcome = Literal["committed", "stale", "stopped"]


def _prescreen_step(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    rubric: RubricText,
    compare_state: CompareState,
    compare_cache: CompareCache,
    progress: CompareProgress,
    rng: np.random.Generator,
    speculating_for: tuple[frozenset[str], str] | None = None,
) -> _StepOutcome:
    """One pick-and-maybe-rule cycle. `speculating_for`, when set, is the on-screen
    (pair, dimension) excluded from the picker and the key any uncommitted result is
    cached under as `compare_cache.speculative*` instead of the live `compare_cache.
    suggestion` — the on-screen suggestion must survive this call either way."""
    start_version = compare_state.version
    progress.version = start_version
    (
        openings,
        assertions_by_opening,
        rulings_by_opening,
        comparisons_by_target,
        companies_by_opening,
    ) = screening_pool_inputs(conn, config)
    pool_result = rank_screening_pool(conn, config, openings=openings)
    p_top_k_by_opening = {r.opening_id: r.p_top_k for r in pool_result.opening_ranks_unguarded}
    picked_at = time.monotonic()
    suggestion = select_comparison(
        [o.id for o in openings],
        companies_by_opening,
        assertions_by_opening,
        comparisons_by_target,
        p_top_k_by_opening,
        config=config,
        rulings_by_opening=rulings_by_opening,
        rng=rng,
        excluded_triples={speculating_for} if speculating_for is not None else None,
    )
    _prescreen_log.info(
        "picker took %.2fs (compare_version=%s)", time.monotonic() - picked_at, start_version
    )
    if suggestion is None:
        if speculating_for is not None:
            _prescreen_log.debug("speculative found nothing beyond the on-screen pair")
        else:
            _cache_operator_suggestion(
                compare_cache, progress, version=start_version, suggestion=None, jev_read=None
            )
            _prescreen_log.debug("prescreen done: nothing left to suggest")
        return "stopped"

    jev_started = time.monotonic()
    comparison, jev_read = _consult_jev_for_suggestion(
        conn,
        suggestion,
        assertions_by_opening,
        rulings_by_opening,
        config,
        verdict_provider=verdict_provider,
        rubric=rubric,
        rng=rng,
    )
    _prescreen_log.info(
        "jev consult took %.2fs on %s (%s vs %s)",
        time.monotonic() - jev_started,
        suggestion.target,
        suggestion.opening_a_id,
        suggestion.opening_b_id,
    )
    if compare_state.version != start_version:
        _prescreen_log.debug("prescreen dropping ruling: version moved during jev consult")
        return "stale"
    if comparison is None:
        if speculating_for is not None:
            _cache_speculative_suggestion(
                compare_cache,
                excluded=speculating_for,
                version=start_version,
                suggestion=suggestion,
                jev_read=jev_read,
            )
            _prescreen_log.debug(
                "speculative cached suggestion for operator (compare_version=%s)", start_version
            )
        else:
            _cache_operator_suggestion(
                compare_cache,
                progress,
                version=start_version,
                suggestion=suggestion,
                jev_read=jev_read,
            )
            _prescreen_log.debug(
                "prescreen cached suggestion for operator (compare_version=%s)", start_version
            )
        return "stopped"

    append_comparison(conn, comparison)
    compare_state.version += 1
    compare_state.last_write = comparison_key(
        comparison.opening_a_id, comparison.opening_b_id, comparison.target
    )
    _prescreen_log.debug(
        "%s auto-ruled %s (%s vs %s) -> compare_version=%s",
        "speculative" if speculating_for is not None else "prescreen",
        comparison.target,
        comparison.opening_a_id,
        comparison.opening_b_id,
        compare_state.version,
    )
    if speculating_for is not None:
        # The on-screen suggestion (`compare_cache.suggestion`/`.jev_read`) belongs to the
        # operator's current page and must survive an auto-ruling that happens behind
        # it — only the shared version/last_write above move, and only `.speculative*`
        # is ever touched for this pass, on a later non-committing step.
        return "committed"
    progress.ruled.append(comparison)
    _cache_operator_suggestion(
        compare_cache,
        progress,
        version=compare_state.version,
        suggestion=None,
        jev_read=None,
    )
    return "committed"


def run_prescreen(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    rubric: RubricText,
    compare_state: CompareState | None = None,
    compare_cache: CompareCache | None = None,
    progress: CompareProgress,
    max_iterations: int = _MAX_SHORT_CIRCUIT_ITERATIONS,
) -> None:
    """Rules every confidently-gated (pair, dimension) ahead of the operator's first
    `/compare` view this pass, persisting each one and appending it to `progress.ruled`
    as it lands — the polling route renders this list live. Stops at the first
    suggestion Jev isn't confident about, when nothing is left to suggest, when the live
    compare-write version changes under it, or at `max_iterations` (a safety bound, not a
    tuned behavior knob)."""
    compare_state = compare_state if compare_state is not None else CompareState()
    compare_cache = compare_cache if compare_cache is not None else CompareCache()
    progress.running = True
    progress.completed = False
    progress.version = compare_state.version
    rng = np.random.default_rng(config.seed)
    started_at = time.monotonic()
    _prescreen_log.debug("prescreen start (compare_version=%s)", compare_state.version)
    try:
        for _ in range(max_iterations):
            outcome = _prescreen_step(
                conn,
                config,
                verdict_provider=verdict_provider,
                rubric=rubric,
                compare_state=compare_state,
                compare_cache=compare_cache,
                progress=progress,
                rng=rng,
            )
            if outcome == "stopped":
                return
    finally:
        progress.running = False
        progress.completed = True
        _prescreen_log.debug(
            "prescreen finished in %.2fs (auto_ruled=%s, cached_suggestion=%s)",
            time.monotonic() - started_at,
            len(progress.ruled),
            progress.final_suggestion is not None,
        )


def run_speculative_prescreen(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    rubric: RubricText,
    compare_state: CompareState,
    compare_cache: CompareCache,
    max_iterations: int = _MAX_SHORT_CIRCUIT_ITERATIONS,
) -> None:
    """Compute what the operator should see *after* the comparison currently on their
    screen, while they are still deciding it. The on-screen triple is excluded from the
    picker, so this answers "what's next" without knowing the outcome — the stale-by-one
    trade. Unlike the authoritative prescreen, this may auto-rule later easy pairs before
    it caches the next usable suggestion.

    Silently returns when the state moved while it was working: the result describes a
    pool that no longer exists, and a stale speculation is worse than none.

    `max_iterations` bounds the auto-ruling chain the same way `run_prescreen`'s does.
    """
    on_screen = compare_cache.suggestion
    if on_screen is None:
        return
    start_version = compare_state.version
    started_at = time.monotonic()
    excluded = comparison_key(on_screen.opening_a_id, on_screen.opening_b_id, on_screen.target)
    _prescreen_log.debug("speculative start (compare_version=%s)", start_version)
    compare_cache.speculative = None
    compare_cache.speculative_jev_read = None
    compare_cache.speculative_for = None
    rng = np.random.default_rng(config.seed)
    expected_version = start_version
    try:
        for _ in range(max_iterations):
            outcome = _prescreen_step(
                conn,
                config,
                verdict_provider=verdict_provider,
                rubric=rubric,
                compare_state=compare_state,
                compare_cache=compare_cache,
                progress=CompareProgress(),
                rng=rng,
                speculating_for=excluded,
            )
            if outcome == "committed":
                expected_version = compare_state.version
                continue
            if compare_state.version != expected_version:
                _prescreen_log.debug("speculative discarded: operator wrote while it was running")
            return
    finally:
        _prescreen_log.debug(
            "speculative finished in %.2fs (cached_suggestion=%s)",
            time.monotonic() - started_at,
            compare_cache.speculative is not None,
        )


def run_speculative_prescreen_in_background(
    db_path: Path,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    rubric: RubricText,
    compare_state: CompareState,
    compare_cache: CompareCache,
) -> None:
    """`run_speculative_prescreen` entry point for `fastapi.BackgroundTasks`, on its own
    connection — same reason as `run_prescreen_in_background`."""
    conn = connect(db_path)
    try:
        run_speculative_prescreen(
            conn,
            config,
            verdict_provider=verdict_provider,
            rubric=rubric,
            compare_state=compare_state,
            compare_cache=compare_cache,
        )
    finally:
        conn.close()


def run_prescreen_in_background(
    db_path: Path,
    config: ScoringConfig,
    *,
    verdict_provider: VerdictProvider,
    rubric: RubricText,
    compare_state: CompareState,
    compare_cache: CompareCache,
    progress: CompareProgress,
) -> None:
    """`run_prescreen` entry point for `fastapi.BackgroundTasks`: opens its own
    connection, since the request that scheduled this has already returned (mirrors
    `BatchEngine.run`)."""
    conn = connect(db_path)
    try:
        run_prescreen(
            conn,
            config,
            verdict_provider=verdict_provider,
            rubric=rubric,
            compare_state=compare_state,
            compare_cache=compare_cache,
            progress=progress,
        )
    finally:
        conn.close()
