"""Unit test for the `cli` Click group — the scaffolding entry point that
lets `uv run python -m screen.intake.cli <command>` reach every backfill
command not wired into the web surface. `intake`, `research`, `research-batch`,
`research-status`, `bump-research-turns-budget`, `backfill-research-turns-budget`
are gone — intake is web-only, the research batch is triggered from the queue
page, and the lifetime per-opening turn budget is retired (research-targeting.md).
"""

from __future__ import annotations

from click.testing import CliRunner

from screen.intake.cli import cli


def test_cli_group_lists_all_scaffolding_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "backfill-digests" in result.output
