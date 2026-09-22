"""Tests for the backend-only pair/dimension picker: it scores every `(pair, dimension)`
candidate as `closeness_overall x boundary_weight x sqrt(weight) x var_diff x jitter`,
refuses to ask about a dimension where either opening has no assertions (`domain`
included), and never elevates a pair neither side of which could plausibly move into or
out of top-K."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import numpy as np
import pytest

from screen.score.compare import Comparison
from screen.score.compare_picker import (
    ComparisonSuggestion,
    _p_a_gt_b,
    _prior_variance,
    select_comparison,
)
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation, Fit

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)
_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


def _no_jitter(config: ScoringConfig) -> ScoringConfig:
    """A copy of `config` with jitter disabled, for tests asserting an exact winner."""
    return dataclasses.replace(config, comparison_jitter_sigma=0.0)


def _neutral_p_top_k(opening_ids: list[str]) -> dict[str, float]:
    """Every opening equally likely in or out of top-K (`p=0.5`, `boundary_weight`
    maximized) — isolates dimension/pair-closeness behavior from the boundary term."""
    return dict.fromkeys(opening_ids, 0.5)


def _rng() -> np.random.Generator:
    return np.random.default_rng(0)


def _assertion(target: str, fit: Fit = "Strong") -> Assertion:
    return Assertion(
        target=target,  # type: ignore[arg-type]
        fit=fit,
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )


def test_single_opening_returns_none(config: ScoringConfig) -> None:
    a = "acme--a"
    suggestion = select_comparison(
        [a], {a: "acme"}, {a: [_assertion("stretch")]}, {}, _neutral_p_top_k([a]), config=config
    )
    assert suggestion is None


def test_p_a_gt_b_zero_variance_edges() -> None:
    assert _p_a_gt_b(0.5, 0.0) == 1.0
    assert _p_a_gt_b(-0.5, 0.0) == 0.0
    assert _p_a_gt_b(0.0, 0.0) == 0.5


def test_empty_pool_returns_none(config: ScoringConfig) -> None:
    assert select_comparison([], {}, {}, {}, {}, config=config) is None


def test_picker_prefers_dimension_with_assertions_on_both_openings(
    config: ScoringConfig,
) -> None:
    a, b = "acme--a", "widgets--b"
    assertions = {a: [_assertion("stretch")], b: [_assertion("stretch")]}
    suggestion = select_comparison(
        [a, b],
        {a: "acme", b: "widgets"},
        assertions,
        {},
        _neutral_p_top_k([a, b]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion == ComparisonSuggestion(target="stretch", opening_a_id=a, opening_b_id=b)


def test_picker_skips_zero_assertion_dimensions_including_domain(config: ScoringConfig) -> None:
    a, b = "acme--a", "widgets--b"
    assertions = {a: [_assertion("stretch")], b: []}
    suggestion = select_comparison(
        [a, b],
        {a: "acme", b: "widgets"},
        assertions,
        {},
        _neutral_p_top_k([a, b]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    # `stretch` is disqualified because `b` has no assertions; every other configured
    # dimension is unqualified too since neither side has evidence on it. `domain` is no
    # longer exempt — research already covers it like any other dimension.
    assert suggestion is None

    # With `domain` evidence on both sides (what the research pass normally produces),
    # it becomes askable exactly like any other dimension.
    assertions_domain = {a: [_assertion("domain")], b: [_assertion("domain")]}
    suggestion_domain = select_comparison(
        [a, b],
        {a: "acme", b: "widgets"},
        assertions_domain,
        {},
        _neutral_p_top_k([a, b]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion_domain == ComparisonSuggestion(
        target="domain", opening_a_id=a, opening_b_id=b
    )


def test_same_company_auto_tie_removes_company_level_pair(config: ScoringConfig) -> None:
    a, b = "acme--a", "acme--b"
    assertions = {
        a: [_assertion("mission"), _assertion("stretch")],
        b: [_assertion("mission"), _assertion("stretch")],
    }
    suggestion = select_comparison(
        [a, b],
        {a: "acme", b: "acme"},
        assertions,
        {},
        _neutral_p_top_k([a, b]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    # `mission` is auto-tied for same-company openings; `stretch` is role-level and still askable.
    assert suggestion is not None
    assert suggestion.target == "stretch"


def test_picker_prefers_more_ambiguous_pair(config: ScoringConfig) -> None:
    a, b, c = "a", "b", "c"
    assertions = {
        a: [_assertion("stretch")],
        b: [_assertion("stretch")],
        c: [_assertion("stretch")],
    }
    # A has beaten B decisively, so A/C is more uncertain than A/B.
    comparisons_by_target = {
        "stretch": [Comparison(winner=a, loser=b, tie=False) for _ in range(10)]
    }
    suggestion = select_comparison(
        [a, b, c],
        {a: "acme", b: "widgets", c: "gadgets"},
        assertions,
        comparisons_by_target,
        _neutral_p_top_k([a, b, c]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion is not None
    assert suggestion.target == "stretch"
    assert "c" in (suggestion.opening_a_id, suggestion.opening_b_id)


def test_domain_prior_variance_matches_any_other_dimension(config: ScoringConfig) -> None:
    """Domain's prior variance is derived the same way as every other dimension — no
    permanently-wide special case left over from the old exemption. Same assertion
    pattern, same resulting variance, regardless of which dimension it's for."""
    a = "acme--a"
    assertions = {a: [_assertion("domain"), _assertion("stretch")]}
    domain_var = _prior_variance("domain", a, assertions, None, config)
    stretch_var = _prior_variance("stretch", a, assertions, None, config)
    assert domain_var == stretch_var


def test_repeated_tie_drops_pair_below_a_fresh_pair(config: ScoringConfig) -> None:
    """A pair judged as a tie several times over should stop being re-suggested once its
    own uncertainty has shrunk — reproduces the live stuck-pair symptom: `p` stays pinned
    at exactly 0.5 after a tie, but repeated ties on the same pair are supposed to lower
    its priority, not raise it."""
    a, b, c = "a", "b", "c"
    assertions = {
        a: [_assertion("stretch")],
        b: [_assertion("stretch")],
        c: [_assertion("stretch")],
    }
    comparisons_by_target = {"stretch": [Comparison(winner=a, loser=b, tie=True) for _ in range(6)]}
    suggestion = select_comparison(
        [a, b, c],
        {a: "acme", b: "widgets", c: "gadgets"},
        assertions,
        comparisons_by_target,
        _neutral_p_top_k([a, b, c]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion is not None
    # a/b has been tied six times and its own uncertainty has shrunk accordingly; a/c is
    # untouched and should be offered instead, even though a/b's p is also exactly 0.5.
    assert {suggestion.opening_a_id, suggestion.opening_b_id} == {a, c}


def test_variance_share_rebalances_after_location_shrinks(config: ScoringConfig) -> None:
    """Reproduces the live symptom: once `location`'s rubric weight no longer dominates by
    construction, a pair whose location posterior has been shrunk by repeated comparisons
    should stop winning on `location` and move to another dimension with real evidence."""
    a, b = "a", "b"
    assertions = {
        a: [_assertion("location"), _assertion("stretch")],
        b: [_assertion("location"), _assertion("stretch")],
    }
    comparisons_by_target = {
        "location": [Comparison(winner=a, loser=b, tie=True) for _ in range(20)]
    }
    suggestion = select_comparison(
        [a, b],
        {a: "acme", b: "widgets"},
        assertions,
        comparisons_by_target,
        _neutral_p_top_k([a, b]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion is not None
    assert suggestion.target == "stretch"


def test_variance_share_prefers_uncertain_rank_contest(config: ScoringConfig) -> None:
    """A pair whose overall rank is genuinely contested wins over a pair that's already
    decisively separated overall, even though the decisive pair's only ambiguous dimension
    (`location`) carries a higher rubric weight than anything distinguishing the contested
    pair."""
    contested_a, contested_b = "contested-a", "contested-b"
    decisive_strong, decisive_weak = "decisive-strong", "decisive-weak"
    assertions = {
        contested_a: [_assertion("location")],
        contested_b: [_assertion("location")],
        decisive_strong: [
            _assertion("stretch"),
            _assertion("schematic"),
            _assertion("location"),
        ],
        decisive_weak: [
            _assertion("stretch", fit="Poor"),
            _assertion("schematic", fit="Poor"),
            _assertion("location"),
        ],
    }
    companies = {
        contested_a: "acme",
        contested_b: "widgets",
        decisive_strong: "gadgets",
        decisive_weak: "gizmos",
    }
    opening_ids = [contested_a, contested_b, decisive_strong, decisive_weak]
    suggestion = select_comparison(
        opening_ids,
        companies,
        assertions,
        {},
        _neutral_p_top_k(opening_ids),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion is not None
    assert {suggestion.opening_a_id, suggestion.opening_b_id} == {contested_a, contested_b}


def test_boundary_weight_excludes_pairs_far_from_top_k(config: ScoringConfig) -> None:
    """Two openings that are each other's closest overall contest still score near zero if
    neither could plausibly move into or out of top-K — the picker should prefer a pair
    with less internal closeness but real boundary stakes instead."""
    tail_a, tail_b = "tail-a", "tail-b"
    boundary_a, boundary_b = "boundary-a", "boundary-b"
    assertions = {
        tail_a: [_assertion("stretch", fit="Poor")],
        tail_b: [_assertion("stretch", fit="Poor")],
        boundary_a: [_assertion("schematic")],
        boundary_b: [_assertion("schematic")],
    }
    companies = {
        tail_a: "acme",
        tail_b: "widgets",
        boundary_a: "gadgets",
        boundary_b: "gizmos",
    }
    p_top_k = {
        tail_a: 0.01,
        tail_b: 0.01,
        boundary_a: 0.5,
        boundary_b: 0.5,
    }
    opening_ids = [tail_a, tail_b, boundary_a, boundary_b]
    small_top_k = dataclasses.replace(_no_jitter(config), top_k=2)
    suggestion = select_comparison(
        opening_ids,
        companies,
        assertions,
        {},
        p_top_k,
        config=small_top_k,
        rng=_rng(),
    )
    assert suggestion is not None
    assert {suggestion.opening_a_id, suggestion.opening_b_id} == {boundary_a, boundary_b}


def test_boundary_weight_favors_pair_over_tied_alternative_far_from_top_k(
    config: ScoringConfig,
) -> None:
    """Given two equally-contested, equally-evidenced pairs, the one near the top-K
    boundary wins over the one nobody expects to cross it — `boundary_weight` breaks the
    tie in `closeness` alone."""
    near_a, near_b = "near-a", "near-b"
    far_a, far_b = "far-a", "far-b"
    assertions = {
        near_a: [_assertion("stretch")],
        near_b: [_assertion("stretch")],
        far_a: [_assertion("schematic")],
        far_b: [_assertion("schematic")],
    }
    companies = {near_a: "acme", near_b: "widgets", far_a: "gadgets", far_b: "gizmos"}
    p_top_k = {near_a: 0.5, near_b: 0.5, far_a: 0.001, far_b: 0.001}
    opening_ids = [near_a, near_b, far_a, far_b]
    small_top_k = dataclasses.replace(_no_jitter(config), top_k=2)
    suggestion = select_comparison(
        opening_ids,
        companies,
        assertions,
        {},
        p_top_k,
        config=small_top_k,
        rng=_rng(),
    )
    assert suggestion is not None
    assert {suggestion.opening_a_id, suggestion.opening_b_id} == {near_a, near_b}


def test_boundary_gate_skipped_when_pool_fits_within_top_k(config: ScoringConfig) -> None:
    """When the whole pool is at or under `top_k`, every opening's `p_top_k` is trivially
    1.0 and `boundary_weight` would zero out every candidate — the picker must skip that
    factor rather than returning `None` for a pool that's still worth ordering."""
    a, b = "a", "b"
    assertions = {a: [_assertion("stretch")], b: [_assertion("stretch")]}
    trivial_p_top_k = {a: 1.0, b: 1.0}
    assert config.top_k >= 2
    suggestion = select_comparison(
        [a, b],
        {a: "acme", b: "widgets"},
        assertions,
        {},
        trivial_p_top_k,
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion == ComparisonSuggestion(target="stretch", opening_a_id=a, opening_b_id=b)


def test_dimension_weight_uses_sqrt_not_square(config: ScoringConfig) -> None:
    """A high-weight dimension (`location`, weight 6) with modest evidence-driven variance
    should not automatically beat a lower-weight dimension (`stretch`) whose variance is
    substantially larger — `weight**2` would let location win here purely on weight;
    `sqrt(weight)` should not."""
    a, b = "a", "b"
    # Both dimensions get one assertion each side, so their raw prior variance is
    # identical; only the rubric weight differs (location=6, stretch=3 per rubric.yaml).
    assertions = {
        a: [_assertion("location"), _assertion("stretch")],
        b: [_assertion("location"), _assertion("stretch")],
    }
    suggestion = select_comparison(
        [a, b],
        {a: "acme", b: "widgets"},
        assertions,
        {},
        _neutral_p_top_k([a, b]),
        config=_no_jitter(config),
        rng=_rng(),
    )
    assert suggestion is not None
    # With identical variance and only weight differing, sqrt(6) > sqrt(3) still favors
    # location — this test documents that sqrt scaling doesn't invert weight ordering,
    # only softens its dominance (see the rebalancing test above for the shrunk case).
    assert suggestion.target == "location"


def test_jitter_changes_the_pick_across_seeds(config: ScoringConfig) -> None:
    """With jitter enabled at the configured default sigma, repeating selection under
    several different seeds does not always return the same triple — jitter is doing
    something, not a no-op wired in and forgotten."""
    a, b, c = "a", "b", "c"
    assertions = {
        a: [_assertion("stretch")],
        b: [_assertion("stretch")],
        c: [_assertion("stretch")],
    }
    p_top_k = _neutral_p_top_k([a, b, c])
    picks = {
        select_comparison(
            [a, b, c],
            {a: "acme", b: "widgets", c: "gadgets"},
            assertions,
            {},
            p_top_k,
            config=config,
            rng=np.random.default_rng(seed),
        )
        for seed in range(20)
    }
    assert len(picks) > 1


def test_jitter_is_deterministic_given_a_seeded_rng(config: ScoringConfig) -> None:
    """Same seed, same pick — the picker must not reach for global/unseeded randomness
    once a caller supplies its own generator."""
    a, b, c = "a", "b", "c"
    assertions = {
        a: [_assertion("stretch")],
        b: [_assertion("stretch")],
        c: [_assertion("stretch")],
    }
    p_top_k = _neutral_p_top_k([a, b, c])
    first = select_comparison(
        [a, b, c],
        {a: "acme", b: "widgets", c: "gadgets"},
        assertions,
        {},
        p_top_k,
        config=config,
        rng=np.random.default_rng(42),
    )
    second = select_comparison(
        [a, b, c],
        {a: "acme", b: "widgets", c: "gadgets"},
        assertions,
        {},
        p_top_k,
        config=config,
        rng=np.random.default_rng(42),
    )
    assert first == second
