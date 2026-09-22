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
from screen.store.db import connect
from screen.store.repo import list_openings


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


@click.group()
def cli() -> None:
    """Scaffolding entry point for the migration/backfill commands
    (`backfill-digests`) that aren't wired into a web surface.
    """


cli.add_command(backfill_digests)
