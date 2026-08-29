"""Repository functions: Company/Opening upsert, Assertion append-and-read,
built on `db.connect` + `mappers`. This is the layer `intake/cli.py` calls;
`mappers.py`/`migrate.py` stay connection-shape-agnostic below it.
"""

import sqlite3

from screen.store.mappers import (
    assertion_from_row,
    assertion_ruling_from_row,
    assertion_ruling_to_row,
    assertion_to_row,
    company_from_row,
    company_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.types import Assertion, AssertionRuling, Company, Opening


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
        """INSERT INTO openings (id, company_id, title, url, research_trace_id, created_at)
           VALUES (:id, :company_id, :title, :url, :research_trace_id, :created_at)
           ON CONFLICT (id) DO UPDATE SET
               company_id = excluded.company_id,
               title = excluded.title,
               url = excluded.url,
               research_trace_id = excluded.research_trace_id,
               created_at = excluded.created_at""",
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
    opening reference of its own (F25/F28: sibling to Assertion, not a copy of
    its foreign keys)."""
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


def list_openings(conn: sqlite3.Connection) -> list[Opening]:
    """Every opening in the DB, oldest first — the queue's candidate set before scoring."""
    rows = conn.execute("SELECT * FROM openings ORDER BY created_at").fetchall()
    return [opening_from_row(dict(row)) for row in rows]
