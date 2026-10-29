"""Unit tests for the click-independent batch engine in `screen.research.batch`."""

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.batch import (
    BatchEngine,
    BatchProgress,
    ResumeResult,
    eligible_weights,
    eta_text,
    resume_opening,
    run_batch,
    run_dispatch,
)
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.research_trace.trace_io import ResearchTraceMissingError, research_trace_path_for
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertions_for_opening,
    get_opening,
    upsert_company,
    upsert_opening,
)
from screen.types import Company, Fit, Opening, Stage, Target
from tests.helpers import canned_assertion, fake_dispatch_deps, seed_opening, seed_research_trace

_QUERY = "extra search"


def _seed_opening_with_trace(
    tmp_path: Path, opening_id: str, *, stage: Stage = "screening"
) -> Path:
    trace_path = research_trace_path_for(tmp_path, f"{opening_id}-trace")
    seed_research_trace(
        trace_path, f"Posting for {opening_id}.", f"https://example.com/{opening_id}"
    )
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn, opening_id, research_trace_id=f"{opening_id}-trace", stage=stage)
    conn.close()
    return trace_path


def _search_then_stop_planner() -> FakePlanner:
    return FakePlanner(sequence=[[SearchAction(query=_QUERY)], [StopAction(reason="done")]])


def _build_engine(tmp_path: Path) -> BatchEngine:
    return BatchEngine(
        planner_factory=_search_then_stop_planner,
        deps_factory=lambda: fake_dispatch_deps(
            browser=FakeBrowser(search_fixtures={_QUERY: []}),
            extractor=FakeExtractor([[canned_assertion()]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
    )


def test_batch_runs_across_openings_in_screening_stage(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng")
    _seed_opening_with_trace(tmp_path, "widgets--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    progress = BatchProgress()
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        progress,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
    )
    conn.close()
    assert total > 0
    assert "acme--eng" in touched
    assert "widgets--eng" in touched
    assert progress.spent == total


def test_batch_progress_reports_eta_from_measured_turn_timing(tmp_path: Path) -> None:
    """`run_batch` records a seconds-per-turn EMA from an injected clock and derives
    `eta_seconds` from it — no timing assumed, only measured (queue-page-cleanup
    bearing, Approach)."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    progress = BatchProgress()
    times = iter([0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
    total, _touched = run_batch(
        conn,
        tmp_path,
        4,
        progress,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
        now_fn=lambda: next(times),
    )
    conn.close()
    assert total == 4
    # Every clock tick advances by 2s, so however many opportunities the block splits
    # into, each measures the same 2s/turn rate and the EMA holds at 2.0.
    assert progress.rate == pytest.approx(2.0)
    assert progress.eta_seconds is None
    assert progress.running is False


def test_batch_progress_records_no_rate_when_no_time_elapsed(tmp_path: Path) -> None:
    """A clock that doesn't advance yields no sample; dividing it in would report a
    zero rate and promise the batch is about to finish."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    progress = BatchProgress()
    total, _touched = run_batch(
        conn,
        tmp_path,
        4,
        progress,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
        now_fn=lambda: 5.0,
    )
    conn.close()
    assert total > 0
    assert progress.rate is None


def test_eta_text_formats_seconds_and_minutes() -> None:
    assert eta_text(45) == "45s"
    assert eta_text(90) == "2m"
    assert eta_text(-5) == "0s"


def test_batch_skips_openings_not_in_screening_stage(tmp_path: Path) -> None:
    """A `pursuing`/`applied`/`closed` opening never gets drawn by the bandit —
    leaving the live queue also leaves the research batch's candidate set."""
    _seed_opening_with_trace(tmp_path, "acme--eng", stage="applied")
    _seed_opening_with_trace(tmp_path, "widgets--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        None,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
    )
    conn.close()
    assert total > 0
    assert "acme--eng" not in touched
    assert "widgets--eng" in touched


def test_batch_with_no_screening_openings_is_a_no_op(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", stage="applied")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        4,
        None,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
    )
    conn.close()
    assert total == 0
    assert touched == []


def test_batch_size_zero_is_a_no_op(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        0,
        None,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
    )
    conn.close()
    assert total == 0
    assert touched == []


def test_batch_revisits_same_opening_across_rounds_within_one_batch(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    total, touched = run_batch(
        conn,
        tmp_path,
        3,
        None,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
    )
    conn.close()
    assert total == 3
    assert touched == ["acme--eng"]


def _seed_assertions(
    tmp_path: Path, opening_id: str, targets: list[Target], count: int, fit: Fit = "Strong"
) -> None:
    conn = connect(tmp_path / "screen.db")
    assertions = [
        canned_assertion(target, fit, "ratified") for target in targets for _ in range(count)
    ]
    append_assertions(conn, assertions, opening_id=opening_id)
    conn.close()


def test_batch_draws_the_higher_uncertainty_opening_more_often(tmp_path: Path) -> None:
    """A wide-half-width (unexamined) opening receives turns more often than one whose
    targets are already heavily, consistently examined, over a batch of many draws."""
    config = load_scoring_config()
    all_targets = list(config.dimension_weights)
    _seed_opening_with_trace(tmp_path, "wide--eng")
    _seed_opening_with_trace(tmp_path, "narrow--eng")
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
        deps=engine.deps_factory(),
        on_draw=lambda event: draws.append(event.opening_id),
    )
    conn.close()
    assert total > 0
    assert draws.count("wide--eng") > draws.count("narrow--eng")


def test_eligible_weights_favors_fresh_and_boundary_openings_over_settled_ones(
    tmp_path: Path,
) -> None:
    """With a pool bigger than `top_k`, the boundary-weighted draw (product of
    uncertainty and `p_top_k`) gives a wholly unexamined opening the most weight.
    A clearly-settled top opening gets more weight than a mediocre one, reflecting
    the shift to upside discovery / validation rather than squabbling over the
    boundary."""
    config = load_scoring_config()
    targets = list(config.dimension_weights)
    for opening_id in [
        "top--eng",
        "bottom--eng",
        "mediocre0--eng",
        "mediocre1--eng",
        "mediocre2--eng",
        "mediocre3--eng",
        "mediocre4--eng",
        "mediocre5--eng",
        "mediocre6--eng",
        "mediocre7--eng",
        "mediocre8--eng",
        "mediocre9--eng",
        "fresh--eng",
    ]:
        _seed_opening_with_trace(tmp_path, opening_id)
    _seed_assertions(tmp_path, "top--eng", targets, 10, fit="Strong")
    _seed_assertions(tmp_path, "bottom--eng", targets, 10, fit="Poor")
    # 10 mediocre openings + top + fresh = 12 non-bottom candidates, above `top_k` (10):
    # the mediocre tier genuinely contests the boundary instead of all fitting inside it.
    for i in range(10):
        _seed_assertions(tmp_path, f"mediocre{i}--eng", targets, 10, fit="Mixed")
    conn = connect(tmp_path / "screen.db")

    weights = eligible_weights(conn, config)
    conn.close()
    assert weights["fresh--eng"] > weights["top--eng"]
    assert weights["top--eng"] > weights["mediocre0--eng"]
    assert weights["mediocre0--eng"] > weights["bottom--eng"]
    assert weights["bottom--eng"] > 0


def test_eligible_weights_keep_a_floor_when_pool_is_wholly_settled(
    tmp_path: Path,
) -> None:
    """A pool no larger than `top_k` still gets a nonzero attention floor, so the
    draw remains possible even when the boundary signal is maximally settled."""
    config = load_scoring_config()
    all_targets = list(config.dimension_weights)
    _seed_opening_with_trace(tmp_path, "wide--eng")
    _seed_opening_with_trace(tmp_path, "narrow--eng")
    _seed_assertions(tmp_path, "narrow--eng", all_targets, 10)
    conn = connect(tmp_path / "screen.db")

    weights = eligible_weights(conn, config)
    conn.close()
    assert weights["wide--eng"] > weights["narrow--eng"]
    assert weights["wide--eng"] > 0
    assert weights["narrow--eng"] > 0


def test_batch_draw_sequence_is_reproducible_for_an_unchanged_snapshot(tmp_path: Path) -> None:
    """Two invocations against identical seed data produce identical draw sequences
    (config.seed determinism)."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    _seed_opening_with_trace(tmp_path, "widgets--eng")
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
        deps=engine.deps_factory(),
        on_draw=lambda event: draws1.append(event.opening_id),
    )
    conn.close()
    tmp_path_2 = tmp_path.parent / f"{tmp_path.name}-replay"
    _seed_opening_with_trace(tmp_path_2, "acme--eng")
    _seed_opening_with_trace(tmp_path_2, "widgets--eng")
    conn2 = connect(tmp_path_2 / "screen.db")
    engine2 = _build_engine(tmp_path_2)
    run_batch(
        conn2,
        tmp_path_2,
        10,
        None,
        planner_factory=engine2.planner_factory,
        deps=engine2.deps_factory(),
        on_draw=lambda event: draws2.append(event.opening_id),
    )
    conn2.close()
    assert draws1 == draws2


def test_batch_engine_opens_own_connection(tmp_path: Path) -> None:
    """The web-route engine opens a fresh connection from the db_path, so the
    background task outlives any request-scoped connection."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    engine = BatchEngine(
        planner_factory=_search_then_stop_planner,
        deps_factory=lambda: fake_dispatch_deps(
            browser=FakeBrowser(search_fixtures={_QUERY: []}),
            extractor=FakeExtractor([[canned_assertion()]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
    )
    progress = BatchProgress()
    engine.run(tmp_path / "screen.db", 2, progress)
    assert progress.running is False
    assert progress.spent == 2


def test_batch_engine_prints_a_draw_trace_line_per_spent_turn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mirrors the retired CLI's `research-batch` stdout trace: one line per spent turn
    naming the opening drawn, its draw probability,
    and its uncertainty rank before/after. `BatchEngine.run` is the web route's only
    call site, so this is the only place left that can print it."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    engine = _build_engine(tmp_path)
    progress = BatchProgress()
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
    _seed_opening_with_trace(tmp_path, "acme--eng")
    engine = BatchEngine(
        planner_factory=lambda: FakePlanner(
            sequence=[[FetchAction(url=url)], [StopAction(reason="done")]]
        ),
        deps_factory=lambda: fake_dispatch_deps(
            browser=FakeBrowser(fetch_fixtures={url: {"raw_content": "content"}}),
            extractor=FakeExtractor([[canned_assertion()]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
    )
    progress = BatchProgress()
    engine.run(tmp_path / "screen.db", 1, progress)
    fresh_conn = connect(tmp_path / "screen.db")
    persisted = assertions_for_opening(fresh_conn, "acme--eng")
    fresh_conn.close()
    assert len(persisted) == 1


def test_batch_turn_spends_multiple_actions_on_one_draw(tmp_path: Path) -> None:
    """A single bandit draw should give the planner up to
    `research_block_turns` actions to work down a line of inquiry on the
    same opening, instead of resetting after one action — the sticky-target continuity
    (sticky target + per-target cap)."""
    url = "https://example.com/acme--eng/second-page"
    _seed_opening_with_trace(tmp_path, "acme--eng")
    engine = BatchEngine(
        planner_factory=lambda: FakePlanner(
            sequence=[
                [SearchAction(query="find page")],
                [FetchAction(url=url)],
                [StopAction(reason="mined out")],
            ]
        ),
        deps_factory=lambda: fake_dispatch_deps(
            browser=FakeBrowser(
                search_fixtures={
                    "find page": [{"url": url, "raw_content": "content", "title": "x"}]
                },
                fetch_fixtures={url: {"raw_content": "content"}},
            ),
            extractor=FakeExtractor([[canned_assertion()]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
    )
    progress = BatchProgress()
    engine.run(tmp_path / "screen.db", 3, progress)
    assert progress.touched == ["acme--eng"]
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
    _seed_opening_with_trace(tmp_path, "acme--eng")
    engine = BatchEngine(
        planner_factory=lambda: FakePlanner(
            sequence=[
                [SearchAction(query="find page")],
                [FetchAction(url=url)],
                [StopAction(reason="mined out")],
            ]
        ),
        deps_factory=lambda: fake_dispatch_deps(
            browser=FakeBrowser(
                search_fixtures={
                    "find page": [{"url": url, "raw_content": "content", "title": "x"}]
                },
                fetch_fixtures={url: {"raw_content": "content"}},
            ),
            extractor=FakeExtractor([[canned_assertion()]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
    )
    engine.run(tmp_path / "screen.db", 2, BatchProgress())
    out = capsys.readouterr().out
    assert out.count("drew acme--eng") == 1
    assert "assertions 0->1" in out
    assert "spent 2 turns" in out
    assert "stopped: turn budget exhausted" in out


def test_batch_turn_reports_no_actions_when_action_cap_is_zero(tmp_path: Path) -> None:
    """A misconfigured `research_block_turns=0` caps every block at zero
    actions rather than crashing — the opening is marked stalled and the batch moves on."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    conn = connect(tmp_path / "screen.db")
    engine = _build_engine(tmp_path)
    zero_cap_config = dataclasses.replace(load_scoring_config(), research_block_turns=0)
    total, touched = run_batch(
        conn,
        tmp_path,
        3,
        None,
        config=zero_cap_config,
        planner_factory=engine.planner_factory,
        deps=engine.deps_factory(),
    )
    conn.close()
    assert total == 0
    assert touched == []


def test_resume_opening_spends_nothing_when_no_budget_remains(tmp_path: Path) -> None:
    """A batch whose remaining budget has run out still calls `resume_opening` for the
    drawn opening; it must return a no-op rather than spend an unbudgeted turn."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, "acme--eng")
    assert opening is not None

    planned: list[str] = []

    class _RecordingPlanner(FakePlanner):
        def plan(self, state: object) -> list[StopAction]:
            planned.append("planned")
            return [StopAction(reason="should not be reached")]

    result = resume_opening(
        conn, tmp_path, opening, 0, deps=fake_dispatch_deps(planner=_RecordingPlanner())
    )
    conn.close()

    assert result == ResumeResult(turns_spent=0, stopped_reason="no remaining budget")
    assert planned == []


def test_resume_opening_raises_on_missing_trace(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Inc", created_at=datetime.now(UTC)))
    opening = Opening(
        id="acme--eng",
        company_id="acme",
        title="Eng",
        url="https://example.com/acme--eng",
        research_trace_id="missing-trace",
        created_at=datetime.now(UTC),
    )
    upsert_opening(conn, opening)

    with pytest.raises(ResearchTraceMissingError):
        resume_opening(conn, tmp_path, opening, 1, deps=fake_dispatch_deps())
    conn.close()


def test_run_dispatch_uses_default_digester_when_none_provided(tmp_path: Path) -> None:
    """The production digester fallback is exercised without making a live BAML call."""
    _seed_opening_with_trace(tmp_path, "acme--eng")
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
        deps=fake_dispatch_deps(
            planner=FakePlanner([[StopAction(reason="default digester test")]]),
            browser=FakeBrowser(),
            extractor=FakeExtractor([[canned_assertion()]]),
            update_digests=_fake_update_digests,
        ),
    )

    assert len(digester_calls) == 1
    call_args, call_kwargs = digester_calls[0]
    assert call_args[0] is conn
    assert call_kwargs["opening_id"] == opening.id
