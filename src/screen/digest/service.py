"""Cache-aware digest generation: the seam that ties `DigesterProtocol`
to the `dimension_digests` cache table.

Staleness key is the assertion count for `(opening_id, target)` — assertions
are append-only (Wall 6), so a monotonic count comparison is exact and
sufficient; no hashing or diffing needed.
"""

import sqlite3
from datetime import datetime

from screen.digest.protocol import DigesterProtocol
from screen.store.repo import assertions_for_opening, get_dimension_digest, insert_dimension_digest
from screen.types import DimensionDigest


def update_digests_for_opening(
    conn: sqlite3.Connection,
    *,
    opening_id: str,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
    force: bool = False,
) -> None:
    """Warm the digest cache for every target that has assertions on this opening.

    Called from the CLI at the end of a research pass, so the rating view never blocks
    on a cold cache; idempotent by the same assertion-count staleness key
    `digest_for_target` uses.
    """
    targets = dict.fromkeys(a.target for a in assertions_for_opening(conn, opening_id))
    for target in targets:
        digest_for_target(
            conn,
            opening_id=opening_id,
            target=target,
            digester=digester,
            rubric_text=rubric_text,
            now=now,
            force=force,
        )


def digest_for_target(
    conn: sqlite3.Connection,
    *,
    opening_id: str,
    target: str,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
    force: bool = False,
) -> str:
    """Return the cached digest text for `(opening_id, target)`. Thin wrapper over
    `digest_record_for_target` for callers that only need the prose, not the version id."""
    return digest_record_for_target(
        conn,
        opening_id=opening_id,
        target=target,
        digester=digester,
        rubric_text=rubric_text,
        now=now,
        force=force,
    ).digest


def digest_record_for_target(
    conn: sqlite3.Connection,
    *,
    opening_id: str,
    target: str,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
    force: bool = False,
) -> DimensionDigest:
    """Return the cached `DimensionDigest` record (prose + durable version id) for
    `(opening_id, target)`, regenerating only when the current assertion count has grown
    past what the cache holds, or when `force` is set (e.g. a backfill that mutated
    assertions out from under the cache). Callers that need to record which digest version
    was shown at judgment time (e.g. `Comparison`) should use this, not `digest_for_target`.
    """
    target_assertions = [a for a in assertions_for_opening(conn, opening_id) if a.target == target]
    current_count = len(target_assertions)
    cached = get_dimension_digest(conn, opening_id, target)
    if not force and cached is not None and cached.assertion_count >= current_count:
        return cached
    digest = digester.digest_dimension(target_assertions, rubric_text)
    return insert_dimension_digest(
        conn,
        opening_id=opening_id,
        target=target,
        digest=digest,
        assertion_count=current_count,
        computed_at=now,
    )
