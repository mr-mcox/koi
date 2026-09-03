"""Unit test for the `cli` Click group — the scaffolding entry point that
lets `uv run python -m screen.intake.cli <command>` reach every command
not wired into the stable `screen/__main__.py` surface."""

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
        "bump-research-turns-budget",
        "intake",
        "research",
        "research-batch",
        "research-status",
    ):
        assert name in result.output
