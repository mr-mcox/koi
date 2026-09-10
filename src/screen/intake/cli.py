"""Click commands for backfill operations.

The intake pipeline itself is web-only and lives in `intake/pipeline.py`; this
module is only the scaffolding entry point for the migration/backfill
commands that aren't wired into a web surface.
"""

from __future__ import annotations

from datetime import UTC, datetime

import click

from screen.digest.service import update_digests_for_opening
from screen.extract.prompt import rubric_text_for_baml
from screen.intake.pipeline import db_path_for
from screen.paths import data_dir
from screen.research.batch import build_digester as _build_digester
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    assertions_for_opening,
    dimension_rulings_for_opening,
    list_openings,
    upsert_dimension_ruling,
    upsert_opening,
)


@click.command()
def backfill_digests() -> None:
    """Warm the digest cache for every opening already in the DB — for use
    after a bulk import or a digest prompt change, not part of normal intake."""
    conn = connect(db_path_for(data_dir()))
    openings = list_openings(conn)
    digester = _build_digester()
    rubric = rubric_text_for_baml()
    for opening in openings:
        update_digests_for_opening(
            conn,
            opening_id=opening.id,
            digester=digester,
            rubric_text=rubric,
            now=datetime.now(UTC),
        )
    click.echo(f"warmed digests for {len(openings)} opening(s)")


@click.command()
def backfill_research_turns_budget() -> None:
    """Reset every opening's research_turns_budget to the current scoring.yaml value.

    A blanket reset, not a fill-if-zero: existing openings created before this dial
    existed default to 0 (migration 0006); openings with a manually bumped budget are
    reset too, same as intake seeding a new opening.
    """
    conn = connect(db_path_for(data_dir()))
    openings = list_openings(conn)
    budget = load_scoring_config().research_turns_budget
    for opening in openings:
        upsert_opening(conn, opening.model_copy(update={"research_turns_budget": budget}))
    click.echo(f"set research_turns_budget={budget} for {len(openings)} opening(s)")


@click.command()
def backfill_dimension_ruling_covered_assertion_ids() -> None:
    """Reset every `DimensionRuling`'s `covered_assertion_ids` to the assertions currently
    filed under its target, for rulings that predate the field (migration 0007).

    A blanket reset, not a fill-if-empty: this approximates each pin's snapshot as "every
    assertion under the target as of the backfill run" rather than "as of the pin's own
    `created_at`" — the exact historical set isn't reconstructable once new assertions
    have already landed, and this is the correction path for that. Manually re-running
    it (e.g. after this command itself) overwrites again, same pattern as
    `backfill-research-turns-budget`.
    """
    conn = connect(db_path_for(data_dir()))
    openings = list_openings(conn)
    updated = 0
    for opening in openings:
        assertion_ids_by_target: dict[str, list[str]] = {}
        for a in assertions_for_opening(conn, opening.id):
            assertion_ids_by_target.setdefault(a.target, []).append(a.id)
        for ruling in dimension_rulings_for_opening(conn, opening.id):
            covered = assertion_ids_by_target.get(ruling.target, [])
            upsert_dimension_ruling(
                conn, ruling.model_copy(update={"covered_assertion_ids": covered})
            )
            updated += 1
    click.echo(f"backfilled covered_assertion_ids for {updated} dimension ruling(s)")


@click.group()
def cli() -> None:
    """Scaffolding entry point for the migration/backfill commands
    (`backfill-research-turns-budget`, `backfill-digests`,
    `backfill-dimension-ruling-covered-assertion-ids`) that aren't wired
    into a web surface.
    """


cli.add_command(backfill_digests)
cli.add_command(backfill_research_turns_budget)
cli.add_command(backfill_dimension_ruling_covered_assertion_ids)
