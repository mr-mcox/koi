"""Process entry point for `python -m screen <command>`: loads `.env`, then runs the
backfill commands against the production collaborators."""

import os

from screen.env import load_env
from screen.intake.cli import cli
from screen.wiring import build_cli_deps

load_env()
cli(obj=build_cli_deps(os.environ))
