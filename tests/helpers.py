"""Shared builders for fakes and fixtures. Every collaborator a test doesn't name gets
an inert fake here, so no test can reach a live adapter by omission."""

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from screen.api.app import AppDeps, Database, create_app
from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.extract.prompt import RubricText
from screen.intake.cli import CliDeps
from screen.intake.fakes import FakeIdentifier
from screen.research.actions import StopAction
from screen.research.batch import BatchEngine, RunDispatchDeps
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.types import Assertion, Citation, IdentificationResult
from screen.verdict.classification_protocol import AssertionClassification
from screen.verdict.fakes import FakeAssertionClassifier
from screen.verdict.protocol import FewShotExample, RubricVerdict

# Synthetic stand-ins for the private values `rubric.yaml` references.
SYNTHETIC_PRIVATE = {"SCREEN_COMPENSATION_BASELINE": "$100,000"}


def synthetic_rubric() -> RubricText:
    return RubricText.load(SYNTHETIC_PRIVATE)


def seed_research_trace(research_trace_path: Path, raw_content: str, url: str) -> None:
    """Write a research trace file with a single tavily_extract event."""
    research_trace_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "tool": "tavily_extract",
        "request": {"urls": [url]},
        "response": {
            "results": [{"url": url, "raw_content": raw_content}],
            "failed_results": [],
        },
    }
    research_trace_path.write_text(json.dumps(event) + "\n", encoding="utf-8")


def canned_citation() -> Citation:
    return Citation(
        url="https://example.com/jobs/42",
        quote="Synthetic fixture content.",
        host="example.com",
        source_provenance="official",
        independent=True,
        source_date=None,
    )


def canned_assertion(target: str = "craft_direction") -> Assertion:
    return Assertion(
        target=target,  # type: ignore[arg-type]
        fit="Strong",
        provenance="model_proposed",
        chunk="Synthetic fixture content.",
        citations=[canned_citation()],
        created_at=datetime.now(UTC),
    )


def fake_identifier(company: str = "Example Co", title: str = "Staff Engineer") -> FakeIdentifier:
    return FakeIdentifier(
        [IdentificationResult(company_name=company, opening_title=title, opening_notes="n")]
    )


def fake_extractor() -> FakeExtractor:
    """Single-call FakeExtractor returning one canned craft_direction assertion."""
    return FakeExtractor([[canned_assertion()]])


def fake_planner(reason: str = "All rubric dimensions addressed.") -> FakePlanner:
    return FakePlanner(sequence=[[StopAction(reason=reason)]])


def fake_digester() -> FakeDigester:
    return FakeDigester(["Synthetic digest."])


def fake_dispatch_deps(**overrides: Any) -> RunDispatchDeps:
    deps = RunDispatchDeps(
        planner=fake_planner(),
        browser=FakeBrowser(),
        extractor=fake_extractor(),
        digester=fake_digester(),
        rubric=synthetic_rubric(),
    )
    return dataclasses.replace(deps, **overrides)


class _UnconsultedVerdictProvider:
    """Fails the test if the compare pre-screen ever consults Jev."""

    def rule(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> RubricVerdict:
        raise AssertionError("verdict provider consulted without a fake configured")


def _intake_not_configured(url: str) -> str:
    raise AssertionError(f"intake ran for {url} without a fake intake_fn")


def fake_app_deps(**overrides: Any) -> AppDeps:
    deps = AppDeps(
        rubric=synthetic_rubric(),
        digester=fake_digester(),
        verdict_provider=_UnconsultedVerdictProvider(),
        batch_engine=BatchEngine(planner_factory=fake_planner, deps_factory=fake_dispatch_deps),
        intake_fn=_intake_not_configured,
    )
    return dataclasses.replace(deps, **overrides)


def fake_cli_deps(db_path: Path, **overrides: Any) -> CliDeps:
    deps = CliDeps(
        db_path=db_path,
        rubric=synthetic_rubric(),
        digester=fake_digester(),
        classifier=FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Strong", confidence=0.9, is_relevant=True, relevance_confidence=0.9
                )
            ]
        ),
    )
    return dataclasses.replace(deps, **overrides)


def make_app(db_path: Path, **overrides: Any) -> FastAPI:
    return create_app(Database(db_path), fake_app_deps(**overrides))
