"""Shared browser seam — the neutral contract between intake and research.

`research/` may not import from `intake/`; this module belongs to neither.
Every call site that fetches a URL by protocol should depend on
`BrowserProtocol`, not on the Tavily SDK directly.
"""

from collections.abc import Iterable
from typing import Any, Protocol, TypedDict, cast, runtime_checkable

from tavily import TavilyClient


class BrowserError(Exception):
    """Raised by BrowserProtocol implementations on fetch failure.

    `details` carries whatever raw information the underlying transport gave
    us (e.g. Tavily's `failed_results` entry or the exception text). Tavily's
    own error message collapses distinct causes (404, bot-block, JS-only
    page, timeout) into the same generic string, so we do not attempt to
    classify further here — callers record `details` verbatim in the trace
    for the operator to inspect.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details if details is not None else {}


class SearchHit(TypedDict, total=False):
    url: str
    raw_content: str
    title: str
    snippet: str


class _TavilyExtractScrape(TypedDict, total=False):
    url: str
    raw_content: str


class _TavilyResponse(TypedDict, total=False):
    results: list[_TavilyExtractScrape]
    failed_results: list[dict[str, Any]]


@runtime_checkable
class BrowserProtocol(Protocol):
    """The shape every browser/fetcher implementation must satisfy."""

    def extract(self, urls: Iterable[str]) -> dict[str, Any]: ...

    def fetch(self, url: str) -> SearchHit: ...

    def search(self, query: str) -> list[SearchHit]: ...


class TavilyBrowser:
    """Real Tavily implementation of BrowserProtocol. Constructor stores the
    API key; no network I/O until extract() or fetch() is called."""

    def __init__(self, api_key: str) -> None:
        self._client = TavilyClient(api_key=api_key)

    def extract(self, urls: Iterable[str]) -> dict[str, Any]:
        try:
            return cast(dict[str, Any], cast(Any, self._client.extract(urls=list(urls))))
        except Exception as exc:
            raise BrowserError(str(exc), details={"exception": str(exc)}) from exc

    def fetch(self, url: str) -> SearchHit:
        """Fetch a single URL and return the first result hit."""
        response = cast(_TavilyResponse, self.extract([url]))
        results = response.get("results") or []
        if results:
            return cast(SearchHit, results[0])
        failed = response.get("failed_results") or []
        if failed:
            raise BrowserError(
                f"fetch failed for {url}: {failed[0]}",
                details={"failed_results": failed},
            )
        raise BrowserError(f"fetch returned no results for {url}", details={"failed_results": []})

    def search(self, query: str) -> list[SearchHit]:
        """Search Tavily and return hits."""
        try:
            response = cast(dict[str, Any], cast(Any, self._client).search(query=query))
        except Exception as exc:
            raise BrowserError(str(exc), details={"exception": str(exc)}) from exc
        results = response.get("results") or []
        hits: list[SearchHit] = []
        for r in results:
            hit: SearchHit = {"url": str(r.get("url", ""))}
            if "title" in r:
                hit["title"] = str(r["title"])
            # Tavily search returns 'content' not 'raw_content'
            raw = r.get("raw_content") or r.get("content")
            if raw is not None:
                hit["raw_content"] = str(raw)
            snippet = r.get("snippet") or r.get("content")
            if snippet is not None:
                hit["snippet"] = str(snippet)
            hits.append(hit)
        return hits
