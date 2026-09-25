"""Shared test fixtures and helpers used by both `tests/cli/` and `tests/intake/`.

Formerly lived in `tests/cli/helpers.py`; moved here when the CLI intake
command was retired and its tests became direct pipeline tests.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.intake.fakes import FakeIdentifier
from screen.research.actions import StopAction
from screen.research.fakes import FakePlanner
from screen.types import Assertion, Citation, IdentificationResult

REPO_ROOT = Path(__file__).resolve().parents[1]


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
