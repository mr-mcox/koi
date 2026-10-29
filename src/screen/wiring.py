"""Production assembly: the one place live adapters are constructed and the process
environment is read. Everything else takes its collaborators as arguments, so a test
can only reach a paid or networked service by building one here.
"""

import functools
from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI

from screen.api.app import AppDeps, Database, create_app
from screen.browser import Browser, TavilyBrowser
from screen.digest.baml_digester import BAMLDigester
from screen.extract.baml_extractor import BAMLExtractor
from screen.extract.prompt import RubricText
from screen.extract.protocol import Extractor
from screen.intake.baml_identifier import BAMLIdentifier
from screen.intake.pipeline import db_path_for, intake_url
from screen.paths import data_dir
from screen.research.baml_planner import BAMLPlanner
from screen.research.batch import BatchEngine, RunDispatchDeps
from screen.score.loader import load_scoring_config
from screen.verdict.jev_assertion_classifier import JevAssertionClassifier
from screen.verdict.jev_verdict_provider import JevVerdictProvider


def build_browser(environ: Mapping[str, str]) -> Browser:
    return TavilyBrowser(api_key=environ.get("TAVILY_API_KEY", ""))


def build_extractor(rubric: RubricText) -> Extractor:
    return BAMLExtractor(JevAssertionClassifier(rubric))


def build_dispatch_deps(rubric: RubricText, environ: Mapping[str, str]) -> RunDispatchDeps:
    return RunDispatchDeps(
        planner=BAMLPlanner(),
        browser=build_browser(environ),
        extractor=build_extractor(rubric),
        digester=BAMLDigester(),
        rubric=rubric,
    )


def build_intake_fn(
    data_root: Path, rubric: RubricText, environ: Mapping[str, str]
) -> Callable[[str], str]:
    """The intake pipeline for one URL."""
    return functools.partial(
        intake_url,
        data_dir=data_root,
        client_factory=lambda: build_browser(environ),
        identifier_factory=BAMLIdentifier,
        extractor_factory=lambda: build_extractor(rubric),
        deps_factory=lambda: build_dispatch_deps(rubric, environ),
    )


def build_app(environ: Mapping[str, str]) -> FastAPI:
    """The served app. Raises `MissingPrivateConfigError` when the rubric's private
    values are unset, so a misconfigured process fails at startup."""
    data_root = data_dir(environ)
    rubric = RubricText.load(environ)
    deps = AppDeps(
        rubric=rubric,
        digester=BAMLDigester(),
        verdict_provider=JevVerdictProvider(load_scoring_config()),
        batch_engine=BatchEngine(
            planner_factory=BAMLPlanner,
            deps_factory=lambda: build_dispatch_deps(rubric, environ),
        ),
        intake_fn=build_intake_fn(data_root, rubric, environ),
    )
    return create_app(Database(db_path_for(data_root)), deps)
