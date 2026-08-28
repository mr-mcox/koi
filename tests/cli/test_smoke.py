"""Smoke test for the CLI entry point itself."""

from __future__ import annotations

import os
import subprocess
import sys

from tests.cli.helpers import REPO_ROOT


def test_cli_help_exits_zero() -> None:
    """`python -m screen --help` exits 0 and documents the URL argument."""
    result = subprocess.run(
        [sys.executable, "-m", "screen", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "")},
    )
    assert result.returncode == 0, (
        f"`python -m screen --help` exited {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "URL" in result.stdout
