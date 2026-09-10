"""Unit tests for the click-independent batch engine in `screen.research.batch`."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.browser import BrowserProtocol
from screen.digest.fakes import FakeDigester
from screen.digest.protocol import DigesterProtocol
from screen.extract.fakes import FakeExtractor
from screen.extract.protocol import ExtractorProtocol
from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.batch import (
    BatchEngine,
    ResearchTraceMissingError,
    build_client,
    build_digester,
    build_extractor,
    build_planner,
    eta_text,
    opening_research_status,
    read_page_content,
    remaining_budget,
    resume_opening,
    run_batch,
    run_dispatch,
)
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.research.protocol import PlannerProtocol
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertions_for_opening,
    get_opening,
    upsert_company,
    upsert_opening,
)
from screen.types import Assertion, Citation, Company, Opening
from tests.cli.helpers import canned_assertion

_QUERY = "extra search"


def _seed_opening_with_trace(
    tmp_path: Path, opening_id: str, company_id: str, *, budget: int, stage: str = "screening"
) -> Path:
    conn = connect(tmp_path / "screen.db")
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    trace_path = tmp_path / "research_traces" / f"{opening_id}-trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://example.com/{opening_id}"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {
                    "results": [{"url": url, "raw_content": f"Posting for {opening_id}."}]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=url,
            research_trace_id=f"{opening_id}-trace",
            research_turns_budget=budget,
            created_at=datetime.now(UTC),
            stage=stage,  # type: ignore[arg-type]
        ),
    )
    conn.close()
    return trace_path


def _search_then_stop_planner() -> FakePlanner:
    return FakePlanner(sequence=[[SearchAction(query=_QUERY)], [StopAction(reason="done")]])


def _build_engine(tmp_path: Path) -> BatchEngine:
    return BatchEngine(
        planner_factory=_search_then_stop_planner,
        browser_factory=lambda: FakeBrowser(search_fixtures={_QUERY: []}),
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        digester_factory=lambda: FakeDigester(["Synthetic digest."]),
    )


def test_batch_runs_across_openings_with_remaining_budget(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=2)
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=2)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    progress: dict[str, object] = {}
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        progress,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total > 0
    assert "acme--eng" in touched
    assert "widgets--eng" in touched
    assert progress["spent"] == total


def test_batch_progress_reports_eta_from_measured_turn_timing(tmp_path: Path) -> None:
    """`run_batch` records a seconds-per-turn EMA from an injected clock and derives
    `eta_seconds` from it — no timing assumed, only measured (queue-page-cleanup
    bearing, Approach)."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=4)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    progress: dict[str, object] = {}
    times = iter([0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
    total, _touched = run_batch(
        conn,
        tmp_path,
        4,
        progress,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
        now_fn=lambda: next(times),
    )
    conn.close()
    assert total == 3  # the seed trace already counts one turn against the budget
    # Every clock tick advances by 2s, so however many opportunities the block splits
    # into, each measures the same 2s/turn rate and the EMA holds at 2.0.
    assert progress["rate"] == pytest.approx(2.0)
    assert progress["eta_seconds"] is None
    assert progress["running"] is False


def test_eta_text_formats_seconds_and_minutes() -> None:
    assert eta_text(45) == "45s"
    assert eta_text(90) == "2m"
    assert eta_text(-5) == "0s"


def test_batch_skips_openings_with_no_remaining_budget(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)  # already exhausted
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=2)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total > 0
    assert "acme--eng" not in touched
    assert "widgets--eng" in touched


def test_batch_skips_openings_not_in_screening_stage(tmp_path: Path) -> None:
    """A `pursuing`/`applied`/`closed` opening never consumes research budget or gets
    drawn by the bandit — leaving the live queue also leaves the research batch's
    candidate set."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5, stage="applied")
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=5)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total > 0
    assert "acme--eng" not in touched
    assert "widgets--eng" in touched


def test_batch_stops_when_all_budgets_exhausted_before_batch_size(tmp_path: Path) -> None:
    """A batch of 10 against one opening with 1 turn remaining spends only that 1 turn."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=2)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        10,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total == 1
    assert touched == ["acme--eng"]


def test_batch_with_no_openings_having_budget_is_a_no_op(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total == 0
    assert touched == []


def test_batch_size_zero_is_a_no_op(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        0,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total == 0
    assert touched == []


def test_batch_revisits_same_opening_across_rounds_within_one_batch(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=4)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        3,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total == 3
    assert touched == ["acme--eng"]


def _seed_assertions(tmp_path: Path, opening_id: str, targets: list[str], count: int) -> None:
    conn = connect(tmp_path / "screen.db")
    assertions = [
        Assertion(
            target=target,  # type: ignore[arg-type]
            fit="Strong",
            provenance="ratified",
            chunk="chunk",
            citations=[
                Citation(
                    url="https://example.com",
                    quote="q",
                    host="example.com",
                    source_provenance="official",
                    independent=True,
                    source_date=None,
                )
            ],
            created_at=datetime.now(UTC),
        )
        for target in targets
        for _ in range(count)
    ]
    append_assertions(conn, assertions, opening_id=opening_id)
    conn.close()


def test_batch_draws_the_higher_uncertainty_opening_more_often(tmp_path: Path) -> None:
    """A wide-half-width (unexamined) opening receives turns more often than one whose
    targets are already heavily, consistently examined, over a batch of many draws."""
    config = load_scoring_config()
    all_targets = list(config.dimension_weights) + list(config.constraints)
    _seed_opening_with_trace(tmp_path, "wide--eng", "wide", budget=50)
    _seed_opening_with_trace(tmp_path, "narrow--eng", "narrow", budget=50)
    _seed_assertions(tmp_path, "narrow--eng", all_targets, 10)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    draws: list[str] = []

    total, _ = run_batch(
        conn,
        tmp_path,
        30,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
        on_draw=lambda event: draws.append(event.opening_id),
    )
    conn.close()
    assert total > 0
    assert draws.count("wide--eng") > draws.count("narrow--eng")


def test_batch_never_draws_a_budget_exhausted_opening(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)  # already exhausted
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=5)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        5,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total > 0
    assert "acme--eng" not in touched


def test_batch_draw_sequence_is_reproducible_for_an_unchanged_snapshot(tmp_path: Path) -> None:
    """Two invocations against identical seed data produce identical draw sequences
    (config.seed determinism)."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=50)
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=50)
    draws1: list[str] = []
    draws2: list[str] = []

    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    run_batch(
        conn,
        tmp_path,
        10,
        None,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
        on_draw=lambda event: draws1.append(event.opening_id),
    )
    conn.close()

    tmp_path_2 = tmp_path.parent / f"{tmp_path.name}-replay"
    _seed_opening_with_trace(tmp_path_2, "acme--eng", "acme", budget=50)
    _seed_opening_with_trace(tmp_path_2, "widgets--eng", "widgets", budget=50)
    conn2 = connect(tmp_path_2 / "screen.db")
    engine2 = _build_engine(tmp_path_2)
    run_batch(
        conn2,
        tmp_path_2,
        10,
        None,
        planner_factory=engine2.planner_factory,
        browser=engine2.browser_factory(),
        extractor=engine2.extractor_factory(),
        digester=engine2.digester_factory(),
        on_draw=lambda event: draws2.append(event.opening_id),
    )
    conn2.close()
    assert draws1 == draws2


def test_batch_engine_opens_own_connection(tmp_path: Path) -> None:
    """The web-route engine opens a fresh connection from the db_path, so the
    background task outlives any request-scoped connection."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=3)
    engine = BatchEngine(
        planner_factory=_search_then_stop_planner,
        browser_factory=lambda: FakeBrowser(search_fixtures={_QUERY: []}),
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        digester_factory=lambda: FakeDigester(["Synthetic digest."]),
    )
    progress: dict[str, object] = {}
    engine.run(tmp_path / "screen.db", 2, progress)
    assert progress["running"] is False
    assert progress["spent"] == 2


def test_batch_engine_prints_a_draw_trace_line_per_spent_turn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mirrors the retired CLI's `research-batch` stdout trace: one line per spent turn
    naming the opening drawn, its draw probability,
    and its uncertainty rank before/after. `BatchEngine.run` is the web route's only
    call site, so this is the only place left that can print it."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=3)
    engine = _build_engine(tmp_path)
    progress: dict[str, object] = {}
    engine.run(tmp_path / "screen.db", 2, progress)

    out = capsys.readouterr().out
    assert out.count("drew acme--eng") == 2


def test_batch_fetch_turn_persists_assertions_visible_to_a_fresh_connection(
    tmp_path: Path,
) -> None:
    """A turn that fetches (not just searches) writes its assertions durably —
    readable from a brand-new connection, not just the one the batch used.
    Regression: every existing batch/engine test only ever exercises a
    search-then-stop planner, so a fetch action's on_assertions -> append_assertions
    path was never exercised at the batch level."""
    url = "https://example.com/acme--eng/second-page"
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=3)
    engine = BatchEngine(
        planner_factory=lambda: FakePlanner(
            sequence=[[FetchAction(url=url)], [StopAction(reason="done")]]
        ),
        browser_factory=lambda: FakeBrowser(fetch_fixtures={url: {"raw_content": "content"}}),
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        digester_factory=lambda: FakeDigester(["Synthetic digest."]),
    )
    progress: dict[str, object] = {}
    engine.run(tmp_path / "screen.db", 1, progress)

    fresh_conn = connect(tmp_path / "screen.db")
    persisted = assertions_for_opening(fresh_conn, "acme--eng")
    fresh_conn.close()
    assert len(persisted) == 1


def test_batch_turn_spends_multiple_actions_on_one_draw(tmp_path: Path) -> None:
    """A single bandit draw should give the planner up to
    `research_target_action_cap` actions to work down a line of inquiry on the
    same opening, instead of resetting after one action — the sticky-target continuity
    (sticky target + per-target cap)."""
    url = "https://example.com/acme--eng/second-page"
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    engine = BatchEngine(
        planner_factory=lambda: FakePlanner(
            sequence=[
                [SearchAction(query="find page")],
                [FetchAction(url=url)],
                [StopAction(reason="mined out")],
            ]
        ),
        browser_factory=lambda: FakeBrowser(
            search_fixtures={"find page": [{"url": url, "raw_content": "content", "title": "x"}]},
            fetch_fixtures={url: {"raw_content": "content"}},
        ),
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        digester_factory=lambda: FakeDigester(["Synthetic digest."]),
    )
    progress: dict[str, object] = {}
    engine.run(tmp_path / "screen.db", 3, progress)

    assert progress["spent"] == 3
    assert progress["touched"] == ["acme--eng"]
    fresh_conn = connect(tmp_path / "screen.db")
    assert len(assertions_for_opening(fresh_conn, "acme--eng")) == 1
    fresh_conn.close()


def test_batch_engine_prints_opportunity_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The console trace is one line per bandit *draw* (opportunity), summarizing
    what changed about that opening: rank, assertions filed, actions spent, and
    stop reason. The stop action itself does not consume a turn, so a block
    budget of 3 with a search+fetch+stop sequence spends 2 turns and ends with
    the planner's stop reason."""
    url = "https://example.com/acme--eng/second-page"
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    engine = BatchEngine(
        planner_factory=lambda: FakePlanner(
            sequence=[
                [SearchAction(query="find page")],
                [FetchAction(url=url)],
                [StopAction(reason="mined out")],
            ]
        ),
        browser_factory=lambda: FakeBrowser(
            search_fixtures={"find page": [{"url": url, "raw_content": "content", "title": "x"}]},
            fetch_fixtures={url: {"raw_content": "content"}},
        ),
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        digester_factory=lambda: FakeDigester(["Synthetic digest."]),
    )
    engine.run(tmp_path / "screen.db", 2, {})

    out = capsys.readouterr().out
    assert out.count("drew acme--eng") == 1
    assert "assertions 0->1" in out
    assert "spent 2 turns" in out
    assert "stopped: turn budget exhausted" in out


def test_resume_opening_returns_no_remaining_budget_when_exhausted(tmp_path: Path) -> None:
    """A direct `resume_opening` call against an already-exhausted opening spends
    nothing and reports why, without touching the planner/browser."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)  # one turn in seed trace
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, "acme--eng")
    assert opening is not None
    result = resume_opening(conn, tmp_path, opening, 1)
    conn.close()
    assert result.turns_spent == 0
    assert result.stopped_reason == "no remaining budget"


def test_batch_turn_reports_no_actions_when_action_cap_is_zero(tmp_path: Path) -> None:
    """A misconfigured `research_target_action_cap=0` caps every block at zero
    actions rather than crashing — the opening is marked stalled and the batch moves on."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    zero_cap_config = dataclasses.replace(load_scoring_config(), research_target_action_cap=0)
    total, touched = run_batch(
        conn,
        tmp_path,
        3,
        None,
        config=zero_cap_config,
        planner_factory=engine.planner_factory,
        browser=engine.browser_factory(),
        extractor=engine.extractor_factory(),
        digester=engine.digester_factory(),
    )
    conn.close()
    assert total == 0
    assert touched == []


def test_remaining_budget_computes_from_trace(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, "acme--eng")
    assert opening is not None
    conn.close()
    assert remaining_budget(tmp_path, opening) == 4  # one tavily_extract turn in seed


def test_opening_research_status_supersedes_cli_status(tmp_path: Path) -> None:
    """The queue page can display the same `turns_used/budget` line the retired
    `research-status` CLI printed."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, "acme--eng")
    assert opening is not None
    conn.close()
    used, budget = opening_research_status(tmp_path, opening)
    assert used == 1
    assert budget == 5


def test_resume_opening_raises_on_missing_trace(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Inc", created_at=datetime.now(UTC)))
    opening = Opening(
        id="acme--eng",
        company_id="acme",
        title="Eng",
        url="https://example.com/acme--eng",
        research_trace_id="missing-trace",
        research_turns_budget=5,
        created_at=datetime.now(UTC),
    )
    upsert_opening(conn, opening)

    with pytest.raises(ResearchTraceMissingError):
        resume_opening(conn, tmp_path, opening, 1)
    conn.close()


def test_default_factories_return_protocol_instances() -> None:
    """The production factory functions are safe to call and satisfy the expected
    protocol types, even though the test suite replaces them with fakes."""
    assert isinstance(build_client(), BrowserProtocol)
    assert isinstance(build_extractor(), ExtractorProtocol)
    assert isinstance(build_digester(), DigesterProtocol)
    assert isinstance(build_planner(), PlannerProtocol)


def test_read_page_content_skips_blank_lines_and_non_tavily_events(
    tmp_path: Path,
) -> None:
    """Blank lines and non-tavily_extract events are ignored; the first
    tavily_extract with raw_content wins."""
    trace_path = tmp_path / "research_traces" / "mixed.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://example.com/mixed"
    trace_path.write_text(
        "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "decide_plan",
                "request": {"opening_id": "x"},
                "response": {"actions": []},
            }
        )
        + "\n\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:01Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {"results": [{"url": url, "raw_content": "The real posting."}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    page_content, found_url = read_page_content(trace_path)
    assert page_content == "The real posting."
    assert found_url == url


def test_read_page_content_skips_empty_results_and_falls_back_to_event_url(
    tmp_path: Path,
) -> None:
    """A tavily_extract event with no results is skipped; the URL on the request is
    used when the first result omits its own url."""
    trace_path = tmp_path / "research_traces" / "empty-then-url.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://example.com/fallback"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {"results": []},
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:01Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {"results": [{"raw_content": "Fallback url content."}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    page_content, found_url = read_page_content(trace_path)
    assert page_content == "Fallback url content."
    assert found_url == url


def test_read_page_content_raises_when_no_extract_event_has_content(
    tmp_path: Path,
) -> None:
    """A trace with only empty or non-tavily events raises ResearchTraceMissingError."""
    trace_path = tmp_path / "research_traces" / "no-content.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": ["https://example.com"]},
                "response": {"results": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchTraceMissingError):
        read_page_content(trace_path)


def test_run_dispatch_uses_default_digester_when_none_provided(tmp_path: Path) -> None:
    """The production digester fallback is exercised without making a live BAML call."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=2)
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, "acme--eng")
    assert opening is not None

    digester_calls: list[tuple[object, ...]] = []

    def _fake_update_digests(*args: object, **kwargs: object) -> None:
        digester_calls.append((args, kwargs))

    run_dispatch(
        conn,
        opening.id,
        "https://example.com/acme--eng",
        [canned_assertion()],
        company_id=opening.company_id,
        page_content="content",
        company_name="Acme Inc",
        opening_title="Eng",
        turn_budget=1,
        turns_used=0,
        planner=FakePlanner([[StopAction(reason="default digester test")]]),
        browser=FakeBrowser(),
        extractor=FakeExtractor([[canned_assertion()]]),
        digester=None,
        update_digests=_fake_update_digests,
    )

    assert len(digester_calls) == 1
    call_args, call_kwargs = digester_calls[0]
    assert call_args[0] is conn
    assert call_kwargs["opening_id"] == opening.id
