"""Hand-written fakes satisfying the intake layer's Protocol surfaces."""

from collections.abc import Iterable
from typing import Any

from screen.browser import BrowserError, SearchHit
from screen.types import IdentificationResult


class FakeTavily:
    """Satisfies `BrowserProtocol`. Construct with a `fixtures` dict keyed by URL. Missing URLs raise."""

    def __init__(self, fixtures: dict[str, dict[str, Any]] | None = None) -> None:
        self._fixtures: dict[str, dict[str, Any]] = dict(fixtures or {})

    def extract(self, urls: Iterable[str]) -> dict[str, Any]:
        merged_results: list[dict[str, Any]] = []
        merged_failed: list[dict[str, Any]] = []
        for url in urls:
            fixture = self._fixtures.get(url)
            if fixture is None:
                merged_failed.append({"url": url, "error": "no fixture for URL"})
                continue
            merged_results.extend(fixture.get("results", []) or [])
            merged_failed.extend(fixture.get("failed_results", []) or [])
        return {"results": merged_results, "failed_results": merged_failed}

    def fetch(self, url: str) -> SearchHit:
        response = self.extract([url])
        if response["failed_results"]:
            raise BrowserError(
                f"no fixture for {url}", details={"failed_results": response["failed_results"]}
            )
        results = response["results"]
        if not results:
            raise BrowserError(f"empty fixture for {url}", details={"failed_results": []})
        return SearchHit(**{k: v for k, v in results[0].items() if k in ("url", "raw_content")})

    def search(self, _query: str) -> list[SearchHit]:  # pragma: no cover
        raise NotImplementedError("FakeTavily.search is not used by intake tests.")


class FakeIdentifier:
    """Satisfies `IdentifierProtocol`. Pops canned results in order; repeats last when exhausted."""

    def __init__(self, results: Iterable[IdentificationResult]) -> None:
        self._results: list[IdentificationResult] = list(results)
        if not self._results:
            raise ValueError("FakeIdentifier requires at least one result")
        self._index = 0

    def identify_opening(self, page_content: str) -> IdentificationResult:
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return self._results[-1]
