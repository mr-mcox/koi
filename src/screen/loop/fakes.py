"""Test doubles for the loop bounded context."""

from collections.abc import Iterable
from typing import Any

from screen.browser import BrowserError, SearchHit
from screen.loop.actions import Action, StopAction
from screen.loop.state import LoopState


class FakePlanner:
    """Iterates a sequence of action lists, one per plan() call.
    Defaults to [[StopAction(reason="Fake stop.")]] if no sequence given.
    """

    def __init__(self, sequence: list[list[Action]] | None = None) -> None:
        if sequence is None:
            sequence = [[StopAction(reason="Fake stop.")]]
        if not sequence:
            raise ValueError("sequence must be non-empty.")
        self._sequence: list[list[Action]] = sequence
        self._index = 0

    def plan(self, _state: LoopState) -> list[Action]:
        result = self._sequence[self._index]
        if self._index < len(self._sequence) - 1:
            self._index += 1
        return list(result)


class FakeBrowser:
    """Test double for BrowserProtocol.
    Raises BrowserError for unknown URLs/queries. search_fixtures maps
    query strings to the hit list they return. fetch_fixtures maps URLs to
    raw content dicts. Records calls for test assertions.
    """

    def __init__(
        self,
        fetch_fixtures: dict[str, dict[str, Any]] | None = None,
        search_fixtures: dict[str, list[SearchHit]] | None = None,
    ) -> None:
        self._fetch_fixtures: dict[str, dict[str, Any]] = dict(fetch_fixtures or {})
        self._search_fixtures: dict[str, list[SearchHit]] = dict(search_fixtures or {})
        self.fetch_calls: list[str] = []
        self.search_calls: list[str] = []
        self.extract_calls: list[list[str]] = []

    def extract(self, urls: Iterable[str]) -> dict[str, Any]:
        url_list = list(urls)
        self.extract_calls.append(url_list)
        results = []
        failed = []
        for url in url_list:
            fixture = self._fetch_fixtures.get(url)
            if fixture is None:
                failed.append({"url": url, "error": "no fixture"})
            else:
                results.append(fixture)
        return {"results": results, "failed_results": failed}

    def fetch(self, url: str) -> SearchHit:
        self.fetch_calls.append(url)
        fixture = self._fetch_fixtures.get(url)
        if fixture is None:
            raise BrowserError(f"FakeBrowser: no fixture for {url}")
        return SearchHit(url=url, raw_content=fixture.get("raw_content", ""))

    def search(self, query: str) -> list[SearchHit]:
        self.search_calls.append(query)
        if query not in self._search_fixtures:
            raise BrowserError(f"FakeBrowser: no search fixture for {query!r}")
        return list(self._search_fixtures[query])
