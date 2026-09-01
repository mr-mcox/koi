"""Cache-aware digest generation: the seam that ties `DigesterProtocol`
to the `dimension_digests` cache table.

Staleness key is the assertion count for `(opening_id, target)` — assertions
are append-only (Wall 6), so a monotonic count comparison is exact and
sufficient; no hashing or diffing needed.
"""

import sqlite3
from datetime import datetime

from screen.digest.protocol import DigesterProtocol
from screen.store.repo import assertions_for_opening, get_dimension_digest, upsert_dimension_digest


def update_digests_for_opening(
    conn: sqlite3.Connection,
    *,
    opening_id: str,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
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
        )


def digest_for_target(
    conn: sqlite3.Connection,
    *,
    opening_id: str,
    target: str,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
) -> str:
    """Return the cached digest for `(opening_id, target)`, regenerating only
    when the current assertion count has grown past what the cache holds.
    """
    target_assertions = [a for a in assertions_for_opening(conn, opening_id) if a.target == target]
    current_count = len(target_assertions)

    cached = get_dimension_digest(conn, opening_id, target)
    if cached is not None and cached.assertion_count >= current_count:
        return cached.digest

    digest = digester.digest_dimension(target_assertions, rubric_text)
    upsert_dimension_digest(
        conn,
        opening_id=opening_id,
        target=target,
        digest=digest,
        assertion_count=current_count,
        computed_at=now,
    )
    return digest
