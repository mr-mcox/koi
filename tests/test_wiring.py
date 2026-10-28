"""Production assembly builds offline from an explicit environment, and refuses to build
when the rubric's private values are missing."""

from pathlib import Path

import pytest

from screen.browser import TavilyBrowser
from screen.digest.baml_digester import BAMLDigester
from screen.extract.baml_extractor import BAMLExtractor
from screen.extract.prompt import MissingPrivateConfigError
from screen.research.baml_planner import BAMLPlanner
from screen.verdict.jev_verdict_provider import JevVerdictProvider
from screen.wiring import build_app, build_dispatch_deps
from tests.helpers import SYNTHETIC_PRIVATE, synthetic_rubric


def _environ(tmp_path: Path) -> dict[str, str]:
    return {**SYNTHETIC_PRIVATE, "SCREEN_DATA_DIR": str(tmp_path), "TAVILY_API_KEY": "k"}


def test_app_uses_the_live_adapters_against_the_configured_data_dir(tmp_path: Path) -> None:
    app = build_app(_environ(tmp_path))

    deps = app.state.deps
    assert app.state.database.db_path == tmp_path.resolve() / "screen.db"
    assert isinstance(deps.digester, BAMLDigester)
    assert isinstance(deps.verdict_provider, JevVerdictProvider)


def test_dispatch_deps_use_the_live_adapters() -> None:
    deps = build_dispatch_deps(synthetic_rubric(), {"TAVILY_API_KEY": "k"})

    assert isinstance(deps.planner, BAMLPlanner)
    assert isinstance(deps.browser, TavilyBrowser)
    assert isinstance(deps.extractor, BAMLExtractor)
    assert isinstance(deps.digester, BAMLDigester)


def test_app_refuses_to_build_without_the_compensation_baseline(tmp_path: Path) -> None:
    """A missing baseline fails at startup, not on the first compensation render."""
    with pytest.raises(MissingPrivateConfigError):
        build_app({"SCREEN_DATA_DIR": str(tmp_path)})
