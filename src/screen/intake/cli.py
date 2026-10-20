"""Click commands for backfill operations.

The intake pipeline itself is web-only and lives in `intake/pipeline.py`; this
module is only the scaffolding entry point for the migration/backfill
commands that aren't wired into a web surface.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import click

from screen.digest.service import digest_for_target, update_digests_for_opening
from screen.extract.baml_extractor import RELEVANCE_DROP_THRESHOLD
from screen.extract.prompt import rubric_text_for_baml, rubric_text_for_dimension
from screen.intake.pipeline import db_path_for
from screen.paths import data_dir
from screen.research.batch import build_digester as _build_digester
from screen.store.db import connect
from screen.store.repo import (
    assertion_rulings_for_opening,
    assertions_for_opening,
    delete_assertion,
    list_openings,
    update_assertion_classification,
)
from screen.types import Assertion
from screen.verdict.classification_protocol import AssertionClassifier
from screen.verdict.jev_assertion_classifier import JevAssertionClassifier


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


def _build_assertion_classifier() -> AssertionClassifier:
    return JevAssertionClassifier()


def _reclassify_one_assertion(
    conn: sqlite3.Connection,
    opening_id: str,
    assertion: Assertion,
    classifier: AssertionClassifier,
    ruled_ids: set[str],
    *,
    dry_run: bool,
) -> bool:
    """Re-classifies one stored assertion; returns True if anything changed (dropped or
    reclassified). Isolated from the command loop so the loop itself stays simple."""
    prefix = "[dry-run] " if dry_run else ""
    classification = classifier.classify(
        rubric_text_for_dimension(assertion.target), assertion.chunk, assertion.target
    )
    should_drop = (
        not classification.is_relevant
        and classification.relevance_confidence >= RELEVANCE_DROP_THRESHOLD
        and assertion.id not in ruled_ids
    )
    if should_drop:
        click.echo(f"{prefix}drop {opening_id} [{assertion.target}]: {assertion.chunk[:60]!r}")
        if not dry_run:
            delete_assertion(conn, assertion.id)
        return True
    if assertion.fit != classification.fit or assertion.confidence != classification.confidence:
        click.echo(
            f"{prefix}reclassify {opening_id} [{assertion.target}]: "
            f"{assertion.fit} -> {classification.fit} (confidence={classification.confidence:.2f})"
        )
        if not dry_run:
            update_assertion_classification(
                conn, assertion.id, fit=classification.fit, confidence=classification.confidence
            )
        return True
    return False


@click.command()
@click.option(
    "--dry-run", is_flag=True, default=False, help="Report what would change without writing."
)
def backfill_jev_classification(dry_run: bool) -> None:
    """Re-classify every stored assertion with Jev: refresh `fit`/`confidence`, and drop
    anything now confidently judged irrelevant. One-time maintenance pass for assertions
    persisted before the Jev classification split (decisions.md E6) — updates rows in
    place, a scoped exception to Wall 6's append-only rule. An assertion the operator has
    already ruled on is never dropped, since a ruling can't be re-pointed at nothing.
    Covers every opening regardless of stage (bearing: cost verified well under budget).
    """
    conn = connect(db_path_for(data_dir()))
    classifier = _build_assertion_classifier()
    digester = _build_digester()
    rubric = rubric_text_for_baml()
    openings = list_openings(conn)
    openings_touched = 0
    for opening in openings:
        assertions = assertions_for_opening(conn, opening.id)
        ruled_ids = {r.assertion_id for r in assertion_rulings_for_opening(conn, opening.id)}
        touched_targets: set[str] = set()
        for assertion in assertions:
            changed = _reclassify_one_assertion(
                conn, opening.id, assertion, classifier, ruled_ids, dry_run=dry_run
            )
            if changed:
                touched_targets.add(assertion.target)
        if touched_targets:
            openings_touched += 1
            if not dry_run:
                for target in touched_targets:
                    digest_for_target(
                        conn,
                        opening_id=opening.id,
                        target=target,
                        digester=digester,
                        rubric_text=rubric,
                        now=datetime.now(UTC),
                        force=True,
                    )
    prefix = "[dry-run] " if dry_run else ""
    click.echo(f"{prefix}backfilled {openings_touched}/{len(openings)} opening(s)")


@click.group()
def cli() -> None:
    """Scaffolding entry point for the migration/backfill commands
    (`backfill-digests`) that aren't wired into a web surface.
    """


cli.add_command(backfill_digests)
cli.add_command(backfill_jev_classification)
