"""Shared builders for fakes and fixtures. Every collaborator a test doesn't name gets
an inert fake here, so no test can reach a live adapter by omission."""

import dataclasses
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from screen.api.app import AppDeps, Database, create_app
from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.extract.prompt import RubricText
from screen.intake.fakes import FakeIdentifier
from screen.research.actions import StopAction
from screen.research.batch import BatchEngine, RunDispatchDeps
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.store.repo import append_assertions, upsert_company, upsert_opening
from screen.types import (
    Assertion,
    Citation,
    Company,
    Fit,
    IdentificationResult,
    Opening,
    Provenance,
    Stage,
    Target,
)
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


def canned_citation(**overrides: Any) -> Citation:
    fields: dict[str, Any] = {
        "url": "https://example.com/jobs/42",
        "quote": "Synthetic fixture content.",
        "host": "example.com",
        "source_provenance": "official",
        "independent": True,
        "source_date": None,
    }
    return Citation(**(fields | overrides))


def canned_assertion(
    target: Target = "craft_direction",
    fit: Fit = "Strong",
    provenance: Provenance = "model_proposed",
    **overrides: Any,
) -> Assertion:
    fields: dict[str, Any] = {
        "target": target,
        "fit": fit,
        "provenance": provenance,
        "chunk": "Synthetic fixture content.",
        "citations": [canned_citation()],
        "created_at": datetime.now(UTC),
    }
    return Assertion(**(fields | overrides))


def seed_opening(
    conn: sqlite3.Connection,
    opening_id: str = "acme--eng-abc123",
    *,
    company_id: str | None = None,
    title: str | None = None,
    research_trace_id: str | None = None,
    stage: Stage = "screening",
    assertions: list[Assertion] | None = None,
    created_at: datetime | None = None,
) -> Opening:
    """Upsert an opening and its company. Unset ids and the title derive from `opening_id`;
    the company id is the part before `--`."""
    created_at = created_at or datetime.now(UTC)
    company_id = company_id or opening_id.split("--", maxsplit=1)[0]
    upsert_company(conn, Company(id=company_id, name=f"{company_id} Inc", created_at=created_at))
    opening = Opening(
        id=opening_id,
        company_id=company_id,
        title=title or f"{opening_id} title",
        url=f"https://example.com/{opening_id}",
        research_trace_id=research_trace_id or f"tx-{opening_id}",
        created_at=created_at,
        stage=stage,
    )
    upsert_opening(conn, opening)
    if assertions:
        append_assertions(conn, assertions, opening_id=opening_id)
    return opening


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


def make_app(db_path: Path, **overrides: Any) -> FastAPI:
    return create_app(Database(db_path), fake_app_deps(**overrides))
