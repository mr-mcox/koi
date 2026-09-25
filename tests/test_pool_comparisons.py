"""Acceptance tests for assembling `DimensionPosterior`s from stored comparisons: a
comparison outcome must change `pool_for_screening`'s rank order end-to-end."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from screen.api.scoring import pool_for_screening
from screen.score.compare import Comparison
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation, Opening

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)
_NOW = datetime(2026, 9, 17, tzinfo=UTC)


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


def _assertion(target: str) -> Assertion:
    return Assertion(
        target=target,  # type: ignore[arg-type]
        fit="Strong",
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )


def _opening(opening_id: str, company_id: str) -> Opening:
    return Opening(
        id=opening_id,
        company_id=company_id,
        title="Staff Engineer",
        url=f"https://example.com/{opening_id}",
        research_trace_id="tx" + "0" * 18,
        created_at=_NOW,
    )


def test_comparison_moves_rank_order_through_pool_for_screening(config: ScoringConfig) -> None:
    """Two openings with identical assertions on `craft_direction` are tied until a comparison
    says B beat A three times; after that B must rank ahead of A."""
    tied = [_assertion("craft_direction")]
    a = _opening("acme--a", "acme")
    b = _opening("widgets--b", "widgets")
    assertions_by_opening = {a.id: tied, b.id: tied}

    baseline = pool_for_screening([a, b], assertions_by_opening, {}, config, top_k=1)
    by_id = {r.opening_id: r for r in baseline.opening_ranks}
    assert by_id[a.id].expected_rank == pytest.approx(by_id[b.id].expected_rank, abs=0.01)

    comparisons_by_target = {
        "craft_direction": [Comparison(winner=b.id, loser=a.id, tie=False) for _ in range(3)]
    }
    result = pool_for_screening(
        [a, b],
        assertions_by_opening,
        {},
        config,
        top_k=1,
        comparisons_by_target=comparisons_by_target,
        companies_by_opening={a.id: "acme", b.id: "widgets"},
    )
    by_id = {r.opening_id: r for r in result.opening_ranks}

    assert by_id[b.id].expected_rank < by_id[a.id].expected_rank


def test_same_company_openings_auto_tie_on_company_level_dimension(config: ScoringConfig) -> None:
    """Two openings at the same company never diverge on a company-level dimension
    (`mission`) absent an explicit comparison — an implicit tie term keeps their fitted
    means equal even when one has stronger role-level evidence elsewhere."""
    a = _opening("acme--a", "acme")
    b = _opening("acme--b", "acme")
    assertions_by_opening = {
        a.id: [_assertion("mission"), _assertion("craft_direction")],
        b.id: [_assertion("mission")],
    }

    result = pool_for_screening(
        [a, b],
        assertions_by_opening,
        {},
        config,
        top_k=1,
        comparisons_by_target={"craft_direction": [Comparison(winner=a.id, loser=b.id, tie=False)]},
        companies_by_opening={a.id: "acme", b.id: "acme"},
    )

    mission_trace = result.dimension_trace["mission"]
    assert mission_trace[0].mean() == pytest.approx(mission_trace[1].mean(), abs=0.05)


def test_stale_comparison_naming_opening_outside_pool_is_ignored(config: ScoringConfig) -> None:
    """A comparison recorded while both openings were in the pool must not crash scoring
    once one of them has moved on (e.g. staged to `applied`) and the pool no longer includes
    it — `rank_screening_pool` passes every stored comparison for the dimension regardless of
    which openings are still live, so `pool_for_screening` must tolerate stale references
    rather than KeyError deep in the fit."""
    a = _opening("acme--a", "acme")
    b = _opening("widgets--b", "widgets")
    assertions_by_opening = {
        a.id: [_assertion("craft_direction")],
        b.id: [_assertion("craft_direction")],
    }
    comparisons_by_target = {
        "craft_direction": [Comparison(winner="moved-on--c", loser=b.id, tie=False)]
    }

    result = pool_for_screening(
        [a, b],
        assertions_by_opening,
        {},
        config,
        top_k=1,
        comparisons_by_target=comparisons_by_target,
        companies_by_opening={a.id: "acme", b.id: "widgets"},
    )

    assert {r.opening_id for r in result.opening_ranks} == {a.id, b.id}
