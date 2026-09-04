"""Unit test for the `cli` Click group — the scaffolding entry point that
lets `uv run python -m screen.intake.cli <command>` reach every command
not wired into the stable `screen/__main__.py` surface. `research`,
`research-batch`, `research-status`, `bump-research-turns-budget` are gone —
superseded by the web queue's batch trigger (research-batch-web-trigger
bearing).
"""

from __future__ import annotations

from click.testing import CliRunner

from screen.intake.cli import cli


def test_cli_group_lists_all_scaffolding_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in (
        "backfill-digests",
        "backfill-research-turns-budget",
        "backfill-dimension-ruling-covered-assertion-ids",
        "intake",
    ):
        assert name in result.output
