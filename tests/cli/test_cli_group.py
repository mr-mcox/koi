"""Unit test for the `cli` Click group — the scaffolding entry point that
lets `uv run python -m screen.intake.cli <command>` reach every backfill
command not wired into the web surface. `intake`, `research`, `research-batch`,
`research-status`, `bump-research-turns-budget` are gone — intake is web-only
and the research batch is triggered from the queue page.
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
    ):
        assert name in result.output
