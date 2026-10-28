"""Unit tests for the `backfill-digests` CLI command — warms the digest cache
for every opening already in the DB, for use after a bulk import or a prompt
change (operator request, digest-latency-and-style)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from screen.digest.fakes import FakeDigester
from screen.intake import cli as cli_module
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    get_dimension_digest,
    upsert_company,
    upsert_opening,
)
from screen.types import Company, Opening
from tests.helpers import canned_assertion, fake_cli_deps


def _seed_opening(db_path: Path, opening_id: str, company_id: str) -> None:
    conn = connect(db_path)
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            created_at=datetime.now(UTC),
        ),
    )
    append_assertions(conn, [canned_assertion("craft_direction")], opening_id=opening_id)
    conn.close()


def test_backfill_digests_warms_every_opening(tmp_path: Path) -> None:
    """Running `backfill-digests` warms the cache for every opening in the DB, not just one."""
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    _seed_opening(tmp_path / "screen.db", "widgets--eng", "widgets")

    result = CliRunner().invoke(
        cli_module.backfill_digests,
        [],
        obj=fake_cli_deps(tmp_path / "screen.db", digester=FakeDigester(["digest"])),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    assert get_dimension_digest(conn, "acme--eng", "craft_direction") is not None
    assert get_dimension_digest(conn, "widgets--eng", "craft_direction") is not None


def test_backfill_digests_reports_opening_count(tmp_path: Path) -> None:
    """CLI output names how many openings were warmed, for operator visibility."""
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")

    result = CliRunner().invoke(
        cli_module.backfill_digests,
        [],
        obj=fake_cli_deps(tmp_path / "screen.db", digester=FakeDigester(["digest"])),
        catch_exceptions=False,
    )

    assert "1 opening" in result.output
