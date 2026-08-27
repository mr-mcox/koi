"""Tests for loop context types: SearchContext and FetchContext.

Pins:
- Both types round-trip through model_dump_json / model_validate_json.
- SearchContext with empty hits is valid.
- FetchContext with targets_added=[] is valid (zero-assertion case is not an error).
- Both types are frozen and extra="forbid".
"""

import pytest
from pydantic import ValidationError

from screen.browser import SearchHit
from screen.loop.context import FetchContext, SearchContext


def _search_hit(url: str = "https://example.com/page") -> SearchHit:
    return SearchHit(url=url, raw_content="Snippet of content.")


class TestSearchContext:
    def test_round_trips(self) -> None:
        ctx = SearchContext(query="Company A staff eng comp", hits=[_search_hit()])
        restored = SearchContext.model_validate_json(ctx.model_dump_json())
        assert restored == ctx

    def test_empty_hits_is_valid(self) -> None:
        ctx = SearchContext(query="something", hits=[])
        assert ctx.hits == []

    def test_round_trips_empty_hits(self) -> None:
        ctx = SearchContext(query="q", hits=[])
        restored = SearchContext.model_validate_json(ctx.model_dump_json())
        assert restored == ctx

    def test_frozen(self) -> None:
        ctx = SearchContext(query="q", hits=[])
        with pytest.raises((TypeError, ValidationError)):
            ctx.query = "changed"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            SearchContext(query="q", hits=[], unexpected="boom")  # type: ignore[call-arg]


class TestFetchContext:
    def test_round_trips(self) -> None:
        ctx = FetchContext(
            url="https://example.com/about",
            targets_added=["stretch", "mission"],
            snippet="First 500 chars of page.",
        )
        restored = FetchContext.model_validate_json(ctx.model_dump_json())
        assert restored == ctx

    def test_empty_targets_added_is_valid(self) -> None:
        """Zero-assertion case must not raise."""
        ctx = FetchContext(
            url="https://example.com/about",
            targets_added=[],
            snippet="Hub page with no useful claims.",
        )
        assert ctx.targets_added == []

    def test_round_trips_empty_targets(self) -> None:
        ctx = FetchContext(url="https://example.com/x", targets_added=[], snippet="")
        restored = FetchContext.model_validate_json(ctx.model_dump_json())
        assert restored == ctx

    def test_frozen(self) -> None:
        ctx = FetchContext(url="https://example.com/x", targets_added=[], snippet="")
        with pytest.raises((TypeError, ValidationError)):
            ctx.url = "changed"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            FetchContext(  # type: ignore[call-arg]
                url="https://example.com/x",
                targets_added=[],
                snippet="",
                unexpected="boom",
            )
