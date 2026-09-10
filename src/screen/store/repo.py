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
    dimension_digest_from_row,
    dimension_digest_to_row,
    dimension_ruling_from_row,
    dimension_ruling_to_row,
    intake_queue_item_from_row,
    intake_queue_item_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Company,
    DimensionDigest,
    DimensionRuling,
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
               (id, company_id, title, url, research_trace_id, research_turns_budget,
                created_at, stage)
           VALUES
               (:id, :company_id, :title, :url, :research_trace_id, :research_turns_budget,
                :created_at, :stage)
           ON CONFLICT (id) DO UPDATE SET
               company_id = excluded.company_id,
               title = excluded.title,
               url = excluded.url,
               research_trace_id = excluded.research_trace_id,
               research_turns_budget = excluded.research_turns_budget,
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
    return [assertion_from_row(dict(row)) for row in rows]


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
    return dimension_digest_from_row(dict(row)) if row is not None else None


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


def upsert_dimension_ruling(conn: sqlite3.Connection, ruling: DimensionRuling) -> None:
    """Upsert by `(opening_id, target)` (Approach: pins are not revertable, but
    resubmission still replaces the value) — relies on the unique constraint from
    migration 0005."""
    conn.execute(
        """INSERT INTO dimension_rulings
               (id, opening_id, target, mean, settledness, created_at, covered_assertion_ids)
           VALUES (:id, :opening_id, :target, :mean, :settledness, :created_at,
                   :covered_assertion_ids)
           ON CONFLICT (opening_id, target) DO UPDATE SET
               id = excluded.id, mean = excluded.mean, settledness = excluded.settledness,
               created_at = excluded.created_at,
               covered_assertion_ids = excluded.covered_assertion_ids""",
        dimension_ruling_to_row(ruling),
    )
    conn.commit()


def dimension_rulings_for_opening(
    conn: sqlite3.Connection, opening_id: str
) -> list[DimensionRuling]:
    rows = conn.execute(
        "SELECT * FROM dimension_rulings WHERE opening_id = ? ORDER BY created_at",
        (opening_id,),
    ).fetchall()
    return [dimension_ruling_from_row(dict(row)) for row in rows]


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


def list_intake_queue(conn: sqlite3.Connection) -> list[IntakeQueueItem]:
    rows = conn.execute("SELECT * FROM intake_queue ORDER BY created_at").fetchall()
    return [intake_queue_item_from_row(dict(row)) for row in rows]
