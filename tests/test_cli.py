"""CLI tests for the composed intake pipeline."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from screen.browser import BrowserError, TavilyBrowser
from screen.extract.fakes import FakeExtractor
from screen.intake import cli as cli_module
from screen.intake.cli import _extract_assertions, _identify_transcript
from screen.intake.fakes import FakeIdentifier, FakeTavily
from screen.loop.actions import StopAction
from screen.loop.fakes import FakePlanner
from screen.types import Assertion, Citation, IdentificationResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["SCREEN_DATA_DIR"] = str(tmp_path)
    env["TAVILY_API_KEY"] = "test-stub-key"
    return env


def _seed_transcript_dir(staging_dir: Path, raw_content: str, url: str) -> None:
    """Create a staging transcript directory with a tavily_extract event."""
    staging_dir.mkdir(parents=True)
    transcript = staging_dir / "transcript.jsonl"
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "tool": "tavily_extract",
        "request": {"urls": [url]},
        "response": {
            "results": [{"url": url, "raw_content": raw_content}],
            "failed_results": [],
        },
    }
    transcript.write_text(json.dumps(event) + "\n", encoding="utf-8")


def _canned_citation() -> Citation:
    return Citation(
        url="https://example.com/jobs/42",
        quote="Synthetic fixture content.",
        host="example.com",
        source_provenance="official",
        independent=True,
        source_date=None,
    )


def _canned_assertion(target: str = "stretch") -> Assertion:
    return Assertion(
        target=target,  # type: ignore[arg-type]
        fit="Strong",
        provenance="model_proposed",
        chunk="Synthetic fixture content.",
        citations=[_canned_citation()],
        created_at=datetime.now(UTC),
    )


def _patch_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute a FakeExtractor for live BAML calls in tests that run to completion."""
    monkeypatch.setattr(
        cli_module,
        "_build_extractor",
        lambda: FakeExtractor([[_canned_assertion()]]),
    )


def _fake_identifier(company: str = "Example Co", title: str = "Staff Engineer") -> FakeIdentifier:
    return FakeIdentifier(
        [IdentificationResult(company_name=company, opening_title=title, opening_notes="n")]
    )


# ---------------------------------------------------------------------------
# Help / smoke
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Full pipeline (URL → company + opening + assertions)
# ---------------------------------------------------------------------------


def test_cli_writes_company_and_opening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The full pipeline fetches a URL and writes company.json + opening.json."""
    url = "https://example.com/jobs/42"
    fake = FakeTavily(
        fixtures={
            url: {
                "results": [{"url": url, "raw_content": "Synthetic job posting fixture."}],
                "failed_results": [],
            }
        }
    )
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=_env(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    company_files = list(tmp_path.rglob("company.json"))
    opening_files = list(tmp_path.rglob("opening.json"))
    assert len(company_files) == 1
    assert len(opening_files) == 1

    company = json.loads(company_files[0].read_text(encoding="utf-8"))
    assert company["name"] == "Example Co"
    assert company["id"] == "example-co"

    opening = json.loads(opening_files[0].read_text(encoding="utf-8"))
    assert opening["title"] == "Staff Engineer"
    assert opening["company_id"] == "example-co"
    assert opening["url"] == url


# ---------------------------------------------------------------------------
# Partial-failure paths (no extractor needed — pipeline fails before extraction)
# ---------------------------------------------------------------------------


def test_cli_records_partial_transcript_on_failed_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `extract` returns failed_results, the pipeline writes the partial event
    and exits non-zero. Error type classification is not built yet."""
    url = "https://nowhere.example/"
    fake = FakeTavily(
        fixtures={
            url: {
                "results": [],
                "failed_results": [{"url": url, "error": "fake says: gone"}],
            }
        }
    )
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=_env(tmp_path), catch_exceptions=False)
    assert result.exit_code != 0
    transcripts = list(tmp_path.rglob("transcript.jsonl"))
    assert len(transcripts) == 1
    lines = transcripts[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert parsed["response"]["failed_results"]


def test_cli_records_partial_transcript_on_search_client_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `client.extract(...)` raises BrowserError, the pipeline writes a
    partial event and exits non-zero via ClickException."""

    def _raise(self, urls):  # type: ignore[no-untyped-def]
        raise BrowserError("simulated transport failure")

    monkeypatch.setattr(TavilyBrowser, "extract", _raise)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.intake,
        ["https://example.com/jobs/42"],
        env=_env(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    transcripts = list(tmp_path.rglob("transcript.jsonl"))
    assert len(transcripts) == 1
    lines = transcripts[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert "error" in parsed["response"]


# ---------------------------------------------------------------------------
# _identify_transcript unit tests
# ---------------------------------------------------------------------------


def test_identify_transcript_writes_company_and_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_identify_transcript` reads the transcript, calls the identifier, and writes the records."""
    url = "https://example.com/jobs/42"
    staging_dir = tmp_path / "abcdef0123456789"
    _seed_transcript_dir(staging_dir, "Synthetic page content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    _identify_transcript(staging_dir / "transcript.jsonl", tmp_path)

    company_files = list(tmp_path.rglob("company.json"))
    opening_files = list(tmp_path.rglob("opening.json"))
    assert len(company_files) == 1
    assert len(opening_files) == 1

    company = json.loads(company_files[0].read_text(encoding="utf-8"))
    assert company["name"] == "Example Co"
    opening = json.loads(opening_files[0].read_text(encoding="utf-8"))
    assert opening["title"] == "Staff Engineer"
    assert opening["transcript_id"] == "abcdef0123456789"


def test_identify_transcript_moves_transcript_under_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After success, the staging dir is gone and the transcript lives inside the opening dir."""
    url = "https://example.com/jobs/42"
    staging_dir = tmp_path / "abcdef0123456789"
    _seed_transcript_dir(staging_dir, "Synthetic content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    _identify_transcript(staging_dir / "transcript.jsonl", tmp_path)
    assert not staging_dir.exists()
    transcripts = list(tmp_path.rglob("transcript.jsonl"))
    assert len(transcripts) == 1
    assert transcripts[0].parent.parent.parent.name == "example-co"


def test_identify_transcript_records_decide_plan_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop's dispatch pass wires on_event to the transcript file, not the
    no-op default — decide_plan events must land alongside tavily_extract."""
    url = "https://example.com/jobs/42"
    staging_dir = tmp_path / "abcdef0123456789"
    _seed_transcript_dir(staging_dir, "Synthetic content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    _identify_transcript(staging_dir / "transcript.jsonl", tmp_path)

    transcript = next(tmp_path.rglob("transcript.jsonl"))
    tools = [
        json.loads(line)["tool"] for line in transcript.read_text(encoding="utf-8").splitlines()
    ]
    assert "decide_plan" in tools


def test_identify_transcript_keeps_staging_dir_when_other_files_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-empty staging directory must survive — other features may deposit files there."""
    staging_dir = tmp_path / "abcdef0123456789"
    _seed_transcript_dir(staging_dir, "x", "https://example.com/jobs/42")
    (staging_dir / "research_notes.md").write_text("private", encoding="utf-8")
    monkeypatch.setattr(cli_module, "_build_identifier", lambda: _fake_identifier(title="Eng"))
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    _identify_transcript(staging_dir / "transcript.jsonl", tmp_path)
    assert not (staging_dir / "transcript.jsonl").exists()
    assert staging_dir.exists()
    assert (staging_dir / "research_notes.md").exists()


def test_identify_transcript_raises_when_transcript_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare id with no transcript.jsonl emits a ClickException."""
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    with pytest.raises(click.ClickException) as exc_info:
        _identify_transcript(tmp_path / "no-such-transcript" / "transcript.jsonl", tmp_path)
    assert "transcript missing" in exc_info.value.message.lower()


def test_identify_transcript_skips_blank_and_non_tavily_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank lines and non-tavily events are skipped; the first tavily_extract with raw_content wins."""
    staging_dir = tmp_path / "abcdef0123456789"
    staging_dir.mkdir(parents=True)
    transcript = staging_dir / "transcript.jsonl"
    url = "https://example.com/jobs/42"
    transcript.write_text(
        "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_search",
                "request": {"query": "x"},
                "response": {"results": [], "failed_results": []},
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:01Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {
                    "results": [{"url": url, "raw_content": "real content"}],
                    "failed_results": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "_build_identifier",
        lambda: FakeIdentifier(
            [IdentificationResult(company_name="Example", opening_title="Eng", opening_notes="n")]
        ),
    )
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    _identify_transcript(transcript, tmp_path)
    opening_files = list(tmp_path.rglob("opening.json"))
    assert len(opening_files) == 1


def test_identify_transcript_errors_when_no_tavily_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transcript with only non-tavily events produces a ClickException."""
    staging_dir = tmp_path / "abcdef0123456789"
    staging_dir.mkdir(parents=True)
    transcript = staging_dir / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_search",
                "request": {"query": "x"},
                "response": {"results": [], "failed_results": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)

    with pytest.raises(click.ClickException) as exc_info:
        _identify_transcript(transcript, tmp_path)
    assert "no tavily_extract" in exc_info.value.message.lower()


def test_identify_transcript_errors_on_event_with_empty_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tavily_extract event with empty results treats the transcript as missing content."""
    staging_dir = tmp_path / "abcdef0123456789"
    staging_dir.mkdir(parents=True)
    transcript = staging_dir / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": ["https://example.com/jobs/42"]},
                "response": {"results": [], "failed_results": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)

    with pytest.raises(click.ClickException) as exc_info:
        _identify_transcript(transcript, tmp_path)
    assert "no tavily_extract" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# assertions.jsonl
# ---------------------------------------------------------------------------


def test_identify_transcript_writes_assertions_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After _identify_transcript, assertions.jsonl exists with at least one valid Assertion."""
    url = "https://example.com/jobs/42"
    staging_dir = tmp_path / "abcdef0123456789"
    _seed_transcript_dir(staging_dir, "Synthetic page content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    _identify_transcript(staging_dir / "transcript.jsonl", tmp_path)

    assertion_files = list(tmp_path.rglob("assertions.jsonl"))
    assert len(assertion_files) == 1, "assertions.jsonl must be written under the opening dir"
    lines = [
        row for row in assertion_files[0].read_text(encoding="utf-8").splitlines() if row.strip()
    ]
    assert len(lines) >= 1, "assertions.jsonl must have at least one row"
    parsed = Assertion.model_validate_json(lines[0])
    assert parsed.target in [
        "stretch",
        "peer",
        "trajectory",
        "mission",
        "agentic",
        "compensation",
        "domain",
        "location",
        "internal_culture",
        "extractive_business",
        "non_scoring:obtainability",
    ]
    assert len(parsed.citations) >= 1


def test_extract_assertions_appends_not_truncates(tmp_path: Path) -> None:
    """_extract_assertions is append-only: a second call appends, not replaces (Wall 6)."""
    opening_dir = tmp_path / "opening"
    opening_dir.mkdir()

    fake_ext = FakeExtractor([[_canned_assertion("stretch")], [_canned_assertion("peer")]])

    _extract_assertions(opening_dir, "https://example.com/jobs/42", "chunk", extractor=fake_ext)
    _extract_assertions(opening_dir, "https://example.com/jobs/42", "chunk", extractor=fake_ext)

    assertions_path = opening_dir / "assertions.jsonl"
    lines = [row for row in assertions_path.read_text(encoding="utf-8").splitlines() if row.strip()]
    assert len(lines) == 2, (
        f"Expected 2 appended assertion lines, got {len(lines)}. "
        "assertions.jsonl must never be opened in write mode."
    )
    first = Assertion.model_validate_json(lines[0])
    second = Assertion.model_validate_json(lines[1])
    assert first.target == "stretch"
    assert second.target == "peer"


def test_extract_assertions_each_line_is_valid_assertion(tmp_path: Path) -> None:
    """Every line in assertions.jsonl must parse as a valid Assertion."""
    opening_dir = tmp_path / "opening"
    opening_dir.mkdir()
    fake_ext = FakeExtractor([[_canned_assertion("mission"), _canned_assertion("domain")]])

    _extract_assertions(opening_dir, "https://example.com/jobs/42", "chunk", extractor=fake_ext)

    assertions_path = opening_dir / "assertions.jsonl"
    lines = [row for row in assertions_path.read_text(encoding="utf-8").splitlines() if row.strip()]
    assert len(lines) == 2
    for line in lines:
        a = Assertion.model_validate_json(line)
        assert a.provenance == "model_proposed"
        assert len(a.citations) >= 1


def _patch_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute a FakePlanner so dispatch completes without calling BAML."""
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(sequence=[[StopAction(reason="All rubric dimensions addressed.")]]),
    )


def test_cli_echoes_stop_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI output contains the stop reason emitted by the dispatcher."""
    url = "https://example.com/jobs/42"
    fake = FakeTavily(
        fixtures={
            url: {
                "results": [{"url": url, "raw_content": "Synthetic job posting fixture."}],
                "failed_results": [],
            }
        }
    )
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=_env(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed:\n{result.output}"
    assert (
        "All rubric dimensions addressed." in result.output
    ), f"Stop reason not in CLI output. Got:\n{result.output}"


def test_cli_dispatch_does_not_re_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatch does not re-write assertions.jsonl: file has same row count after dispatch."""
    url = "https://example.com/jobs/42"
    fake = FakeTavily(
        fixtures={
            url: {
                "results": [{"url": url, "raw_content": "Synthetic job posting fixture."}],
                "failed_results": [],
            }
        }
    )
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", _fake_identifier)
    _patch_extractor(monkeypatch)
    _patch_planner(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=_env(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0
    assertion_files = list(tmp_path.rglob("assertions.jsonl"))
    assert len(assertion_files) == 1
    lines = [
        row for row in assertion_files[0].read_text(encoding="utf-8").splitlines() if row.strip()
    ]
    # FakeExtractor returned exactly one assertion; dispatch must not add more.
    assert len(lines) == 1
    Assertion.model_validate_json(lines[0])  # must be valid
