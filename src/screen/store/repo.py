"""Repository functions: Company/Opening upsert, Assertion append-and-read,
built on `db.connect` + `mappers`. This is the layer `intake/cli.py` calls;
`mappers.py`/`migrate.py` stay connection-shape-agnostic below it.
"""

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from screen.store.mappers import (
    assertion_from_row,
    assertion_ruling_from_row,
    assertion_ruling_to_row,
    assertion_to_row,
    company_from_row,
    company_to_row,
    comparison_from_row,
    comparison_to_row,
    dimension_digest_from_row,
    dimension_digest_to_row,
    intake_queue_item_from_row,
    intake_queue_item_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Company,
    Comparison,
    DimensionDigest,
    IntakeQueueItem,
    Opening,
)


def upsert_company(conn: sqlite3.Connection, company: Company) -> None:
    conn.execute(
        """INSERT INTO companies (id, name, created_at)
           VALUES (:id, :name, :created_at)
           ON CONFLICT (id) DO UPDATE SET name = excluded.name, created_at = excluded.created_at""",
        company_to_row(company),
    )
    conn.commit()


def upsert_opening(conn: sqlite3.Connection, opening: Opening) -> None:
    conn.execute(
        """INSERT INTO openings
               (id, company_id, title, url, research_trace_id,
                created_at, stage)
           VALUES
               (:id, :company_id, :title, :url, :research_trace_id,
                :created_at, :stage)
           ON CONFLICT (id) DO UPDATE SET
               company_id = excluded.company_id,
               title = excluded.title,
               url = excluded.url,
               research_trace_id = excluded.research_trace_id,
               created_at = excluded.created_at,
               stage = excluded.stage""",
        opening_to_row(opening),
    )
    conn.commit()


def append_assertions(
    conn: sqlite3.Connection, assertions: list[Assertion], *, opening_id: str
) -> None:
    """Assertions are append-only (Wall 6) — never updated or replaced."""
    conn.executemany(
        """INSERT INTO assertions
           (id, opening_id, target, fit, provenance, chunk, citations, created_at)
           VALUES (:id, :opening_id, :target, :fit, :provenance, :chunk, :citations, :created_at)""",
        [assertion_to_row(a, opening_id=opening_id) for a in assertions],
    )
    conn.commit()


def assertions_for_opening(conn: sqlite3.Connection, opening_id: str) -> list[Assertion]:
    rows = conn.execute(
        "SELECT * FROM assertions WHERE opening_id = ? ORDER BY created_at", (opening_id,)
    ).fetchall()
    return [a for a in (assertion_from_row(dict(row)) for row in rows) if a is not None]


def upsert_assertion_ruling(conn: sqlite3.Connection, ruling: AssertionRuling) -> None:
    """Upsert by `assertion_id` (Approach: repeated ratings replace the previous one,
    not append) — the corpus is a calibration record, one ruling per assertion, not an
    event log. Relies on the unique index on `assertion_rulings.assertion_id`."""
    conn.execute(
        """INSERT INTO assertion_rulings (id, assertion_id, fit, created_at)
           VALUES (:id, :assertion_id, :fit, :created_at)
           ON CONFLICT (assertion_id) DO UPDATE SET
               id = excluded.id, fit = excluded.fit, created_at = excluded.created_at""",
        assertion_ruling_to_row(ruling),
    )
    conn.commit()


def assertion_rulings_for_opening(
    conn: sqlite3.Connection, opening_id: str
) -> list[AssertionRuling]:
    """Every recorded ruling against any assertion belonging to this opening,
    joined through `assertions.opening_id` since `assertion_rulings` carries no
    opening reference of its own — it is a sibling to Assertion, not a copy of its
    foreign keys."""
    rows = conn.execute(
        """SELECT assertion_rulings.*
           FROM assertion_rulings
           JOIN assertions ON assertions.id = assertion_rulings.assertion_id
           WHERE assertions.opening_id = ?
           ORDER BY assertion_rulings.created_at""",
        (opening_id,),
    ).fetchall()
    return [assertion_ruling_from_row(dict(row)) for row in rows]


def get_company(conn: sqlite3.Connection, company_id: str) -> Company | None:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    return company_from_row(dict(row)) if row is not None else None


def get_opening(conn: sqlite3.Connection, opening_id: str) -> Opening | None:
    row = conn.execute("SELECT * FROM openings WHERE id = ?", (opening_id,)).fetchone()
    return opening_from_row(dict(row)) if row is not None else None


def list_openings(conn: sqlite3.Connection, *, stage: str | None = None) -> list[Opening]:
    """Every opening in the DB, oldest first — the queue's candidate set before scoring.

    `stage=None` (default) returns every opening regardless of stage — used by the
    filter-by-stage view and backfill commands, which need to see everything. Callers
    that build the ranked queue, the bandit's eligible-weights set, and the research
    batch's candidate set pass `stage="screening"` so a de-queued opening can never
    anchor the top_k boundary or consume research budget.
    """
    if stage is None:
        rows = conn.execute("SELECT * FROM openings ORDER BY created_at").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM openings WHERE stage = ? ORDER BY created_at", (stage,)
        ).fetchall()
    return [opening_from_row(dict(row)) for row in rows]


def get_dimension_digest(
    conn: sqlite3.Connection, opening_id: str, target: str
) -> DimensionDigest | None:
    row = conn.execute(
        "SELECT * FROM dimension_digests WHERE opening_id = ? AND target = ?",
        (opening_id, target),
    ).fetchone()
    if row is None:
        return None
    return dimension_digest_from_row(dict(row))


def upsert_dimension_digest(
    conn: sqlite3.Connection,
    *,
    opening_id: str,
    target: str,
    digest: str,
    assertion_count: int,
    computed_at: datetime,
) -> None:
    record = DimensionDigest.model_validate(
        {
            "opening_id": opening_id,
            "target": target,
            "digest": digest,
            "assertion_count": assertion_count,
            "computed_at": computed_at,
        }
    )
    conn.execute(
        """INSERT INTO dimension_digests (opening_id, target, digest, assertion_count, computed_at)
           VALUES (:opening_id, :target, :digest, :assertion_count, :computed_at)
           ON CONFLICT (opening_id, target) DO UPDATE SET
               digest = excluded.digest,
               assertion_count = excluded.assertion_count,
               computed_at = excluded.computed_at""",
        dimension_digest_to_row(record),
    )
    conn.commit()


def append_comparison(conn: sqlite3.Connection, comparison: Comparison) -> None:
    """Comparisons are append-only — never updated or replaced; a re-judged pair adds a
    new row, it doesn't overwrite the old one."""
    conn.execute(
        """INSERT INTO comparisons
           (id, opening_a_id, opening_b_id, target, outcome, predicted_a_beats_b,
            opening_a_digest_version, opening_b_digest_version, created_at)
           VALUES
           (:id, :opening_a_id, :opening_b_id, :target, :outcome, :predicted_a_beats_b,
            :opening_a_digest_version, :opening_b_digest_version, :created_at)""",
        comparison_to_row(comparison),
    )
    conn.commit()


def comparisons_for_target(conn: sqlite3.Connection, target: str) -> list[Comparison]:
    """Every comparison recorded against one dimension, oldest first — the batch fit's
    input before it reduces to the latest judgment per (unordered pair, dimension)."""
    rows = conn.execute(
        "SELECT * FROM comparisons WHERE target = ? ORDER BY created_at", (target,)
    ).fetchall()
    return [c for c in (comparison_from_row(dict(row)) for row in rows) if c is not None]


def enqueue_intake_url(conn: sqlite3.Connection, url: str) -> IntakeQueueItem:
    """Insert one pending row and commit before returning — the web submit
    handler relies on this being durable (row survives a crash) before it
    responds. Queuing itself is a blocking write; only the processing that
    follows is backgrounded (see `intake/worker.py`)."""
    item = IntakeQueueItem(id=str(uuid4()), url=url, created_at=datetime.now(UTC))
    conn.execute(
        """INSERT INTO intake_queue (id, url, status, error, created_at)
           VALUES (:id, :url, :status, :error, :created_at)""",
        intake_queue_item_to_row(item),
    )
    conn.commit()
    return item


def claim_next_pending_intake_url(conn: sqlite3.Connection) -> IntakeQueueItem | None:
    """Atomically claim the oldest `pending` row by moving it to `running` and
    returning it, or `None` if the queue is empty."""
    row = conn.execute(
        "SELECT * FROM intake_queue WHERE status = 'pending' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    item = intake_queue_item_from_row(dict(row))
    conn.execute("UPDATE intake_queue SET status = 'running' WHERE id = ?", (item.id,))
    conn.commit()
    return item.model_copy(update={"status": "running"})


def mark_intake_url_done(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute("UPDATE intake_queue SET status = 'done' WHERE id = ?", (item_id,))
    conn.commit()


def mark_intake_url_failed(conn: sqlite3.Connection, item_id: str, error: str) -> None:
    conn.execute(
        "UPDATE intake_queue SET status = 'failed', error = ? WHERE id = ?", (error, item_id)
    )
    conn.commit()


def reset_intake_url_to_pending(conn: sqlite3.Connection, item_id: str) -> None:
    """Requeue a failed row for another worker pass. No-op on a row that
    isn't `failed` — a done or already-pending/running row is never bumped
    back to pending by a stray retry click."""
    conn.execute(
        "UPDATE intake_queue SET status = 'pending', error = NULL "
        "WHERE id = ? AND status = 'failed'",
        (item_id,),
    )
    conn.commit()


def list_intake_queue(conn: sqlite3.Connection) -> list[IntakeQueueItem]:
    rows = conn.execute("SELECT * FROM intake_queue ORDER BY created_at").fetchall()
    return [intake_queue_item_from_row(dict(row)) for row in rows]
