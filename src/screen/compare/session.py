"""The in-process compare session: the pre-screen's cache and progress, and the rules
for whether a cached suggestion may still be served to the operator.

Single-uvicorn-worker assumption; not persisted.
"""

import logging
import sqlite3
from dataclasses import dataclass, field

from screen.compare.picker import ComparisonSuggestion
from screen.compare.prescreen import CompareCache, CompareProgress, CompareState, comparison_key
from screen.score.types import ScoringConfig
from screen.store.repo import get_opening

# Throughput instrumentation for the compare loop: every cache decision is logged so a
# live session can be read back for where the operator waited.
_compare_log = logging.getLogger("screen.compare")


@dataclass
class CompareSession:
    """Everything the compare routes and their background passes share.
    `speculation_in_flight_for` is the on-screen triple a speculative pass is running
    for, so repeated renders of one page don't each queue another."""

    state: CompareState = field(default_factory=CompareState)
    cache: CompareCache = field(default_factory=CompareCache)
    progress: CompareProgress = field(default_factory=CompareProgress)
    speculation_in_flight_for: tuple[frozenset[str], str] | None = None


def needs_prescreen(session: CompareSession) -> bool:
    """No pass is running and the last one ran against an older compare version."""
    return not session.progress.running and session.progress.version != session.state.version


def illegal_suggestion_reason(
    conn: sqlite3.Connection,
    config: ScoringConfig,
    suggestion: ComparisonSuggestion,
) -> str | None:
    """Why this pair/dimension can no longer be rendered, or `None` if it still can."""
    if suggestion.target not in config.dimension_weights:
        return "invalid-target"
    if suggestion.opening_a_id == suggestion.opening_b_id:
        return "degenerate-pair"
    missing = any(
        get_opening(conn, opening_id) is None
        for opening_id in (suggestion.opening_a_id, suggestion.opening_b_id)
    )
    return "missing-opening" if missing else None


def staleness_rejection(
    compare_state: CompareState,
    compare_cache: CompareCache,
    suggestion: ComparisonSuggestion,
) -> str | None:
    """Stale-by-one is accepted; anything older, or a suggestion naming the pair the
    operator just ruled on, is not."""
    behind = compare_state.version - compare_cache.version
    if behind <= 0:
        return None
    if behind > 1:
        return "too-stale"
    just_written = compare_state.last_write == comparison_key(
        suggestion.opening_a_id, suggestion.opening_b_id, suggestion.target
    )
    return "just-written-pair" if just_written else None


def cache_rejection(
    conn: sqlite3.Connection, config: ScoringConfig, session: CompareSession
) -> str | None:
    """Why the cached suggestion can't be served, or `None` when it can. The reason
    string is the instrumentation surface: a live session's log says whether a wait was a
    cache miss, a staleness rejection, or the pre-screen simply not being done yet."""
    suggestion = session.cache.suggestion
    if suggestion is None:
        return "empty"
    illegal = illegal_suggestion_reason(conn, config, suggestion)
    if illegal is not None:
        return illegal
    return staleness_rejection(session.state, session.cache, suggestion)


def claim_speculation(session: CompareSession, on_screen: ComparisonSuggestion) -> bool:
    """Whether to speculate on what follows `on_screen`, marking it in flight if so. False
    when a speculation for this exact triple is already cached or running."""
    on_screen_key = comparison_key(on_screen.opening_a_id, on_screen.opening_b_id, on_screen.target)
    if on_screen_key in (session.cache.speculative_for, session.speculation_in_flight_for):
        return False
    session.speculation_in_flight_for = on_screen_key
    return True


def record_operator_write(session: CompareSession, judged: tuple[frozenset[str], str]) -> None:
    """Advance the compare version past an operator ruling on `judged`, then promote the
    speculation computed during their thinking time into the live suggestion.

    The speculation was computed with `judged` excluded but without knowing its outcome,
    so it is stale-by-one by construction and is published at the *previous* version to
    say so — `staleness_rejection` then vets it on the ordinary path rather than it being
    waved through as fresh. A speculation computed against a different on-screen pair is
    not promoted: it answers a question the operator didn't end up being asked."""
    session.state.version += 1
    session.state.last_write = judged
    session.speculation_in_flight_for = None
    cache = session.cache
    if cache.speculative is None or cache.speculative_for != judged:
        return
    _compare_log.info(
        "promoting speculation to live suggestion (compare_version=%s)", session.state.version
    )
    cache.version = session.state.version - 1
    cache.suggestion = cache.speculative
    cache.jev_read = cache.speculative_jev_read
    cache.speculative = None
    cache.speculative_jev_read = None
    cache.speculative_for = None
