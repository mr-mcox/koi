"""Shared fixtures/helpers for `tests/cli/*` — the CLI entry point's test suite,
split by seam (smoke, full-pipeline, `_identify_research_trace`, `_extract_assertions`).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.intake import cli as cli_module
from screen.intake.fakes import FakeIdentifier
from screen.research.actions import StopAction
from screen.research.fakes import FakePlanner
from screen.types import Assertion, Citation, IdentificationResult

REPO_ROOT = Path(__file__).resolve().parents[2]


def env_for(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["SCREEN_DATA_DIR"] = str(tmp_path)
    env["TAVILY_API_KEY"] = "test-stub-key"
    return env


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


def canned_assertion(target: str = "stretch") -> Assertion:
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


def patch_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute a FakeExtractor for live BAML calls in tests that run to completion."""
    monkeypatch.setattr(
        cli_module,
        "_build_extractor",
        lambda: FakeExtractor([[canned_assertion()]]),
    )


def patch_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute a FakePlanner so dispatch completes without calling BAML."""
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(sequence=[[StopAction(reason="All rubric dimensions addressed.")]]),
    )


def patch_digester(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute a FakeDigester so post-pass digest warming completes without calling BAML."""
    monkeypatch.setattr(
        cli_module,
        "_build_digester",
        lambda: FakeDigester(["Synthetic digest."]),
    )
