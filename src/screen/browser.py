"""Shared browser seam — the neutral contract between intake and research.

`research/` may not import from `intake/`; this module belongs to neither.
Call sites depend on the narrowest protocol they use — `Fetcher` for intake,
`Browser` for research — never on the Tavily SDK directly.
"""

import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypedDict, cast

from tavily import TavilyClient

_MAX_FETCH_ATTEMPTS = 2
# Unmeasured; the observed recoveries were 4s apart. Named so a sweep has
# something to vary.
_RETRY_BACKOFF_SECONDS = 2.0

# Tavily error substrings meaning the link is gone, as opposed to the generic
# "Failed to fetch url" it returns for every transient cause. Entries here
# suppress the retry, so only unambiguous ones belong.
_PERMANENT_ERROR_MARKERS: tuple[str, ...] = ("404",)


class BrowserError(Exception):
    """Raised by Browser implementations on fetch failure.

    `details` carries whatever raw information the underlying transport gave
    us (e.g. Tavily's `failed_results` entry or the exception text). Tavily's
    own error message collapses distinct causes (404, bot-block, JS-only
    page, timeout) into the same generic string, so we do not attempt to
    classify further here — callers record `details` verbatim in the trace
    for the operator to inspect.

    `permanent` is the lone exception: True only when a retry provably cannot
    help. It defaults False so an unrecognized failure stays retryable.
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        permanent: bool = False,
    ) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details if details is not None else {}
        self.permanent = permanent


def failures_are_permanent(failed_results: Iterable[dict[str, Any]]) -> bool:
    """True when every failure is provably hopeless. Conjunctive and
    empty-false: one unrecognized error keeps the fetch retryable."""
    failures = list(failed_results)
    return bool(failures) and all(
        any(marker in str(f.get("error", "")) for marker in _PERMANENT_ERROR_MARKERS)
        for f in failures
    )


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


class _TavilySearchResult(TypedDict, total=False):
    url: str
    title: str
    raw_content: str | None
    content: str | None
    snippet: str | None


class _TavilySearchResponse(TypedDict, total=False):
    results: list[_TavilySearchResult]


class Fetcher(Protocol):
    """Fetches one URL's page content."""

    def fetch(self, url: str) -> SearchHit: ...


class Browser(Fetcher, Protocol):
    """Fetches pages and searches the web."""

    def search(self, query: str) -> list[SearchHit]: ...


class TavilyBrowser:
    """Real Tavily implementation of Browser. Constructor stores the
    API key; no network I/O until fetch() or search() is called."""

    def __init__(
        self,
        api_key: str,
        *,
        client: TavilyClient | None = None,
        retry_backoff_seconds: float = _RETRY_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client if client is not None else TavilyClient(api_key=api_key)
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep

    def _extract(self, urls: Iterable[str]) -> dict[str, Any]:
        try:
            return cast(
                dict[str, Any],
                cast(Any, self._client.extract(urls=list(urls), extract_depth="advanced")),
            )
        except Exception as exc:
            raise BrowserError(str(exc), details={"exception": str(exc)}) from exc

    def _fetch_once(self, url: str) -> SearchHit | BrowserError:
        """One attempt: the hit, or the error a retry would face."""
        try:
            response = cast(_TavilyResponse, self._extract([url]))
        except BrowserError as exc:
            return exc
        results = response.get("results") or []
        if results:
            return cast(SearchHit, results[0])
        failed = response.get("failed_results") or []
        if failed:
            return BrowserError(
                f"fetch failed for {url}: {failed[0]}",
                details={"failed_results": failed},
                permanent=failures_are_permanent(failed),
            )
        return BrowserError(f"fetch returned no results for {url}", details={"failed_results": []})

    def fetch(self, url: str) -> SearchHit:
        """Fetch a single URL and return the first result hit.

        Retries once, after a backoff. Extraction against bot-protected and
        JS-rendered pages fails in bursts — the same input fails and then
        succeeds seconds later, depending on which egress IP is drawn — so an
        immediate second attempt draws from the same bad window. A `permanent`
        failure skips the retry. Retries are free: Tavily bills only
        successful extractions.
        """
        last_error = BrowserError(
            f"fetch returned no results for {url}", details={"failed_results": []}
        )
        for attempt in range(_MAX_FETCH_ATTEMPTS):
            outcome = self._fetch_once(url)
            if not isinstance(outcome, BrowserError):
                return outcome
            last_error = outcome
            if last_error.permanent:
                break
            if attempt + 1 < _MAX_FETCH_ATTEMPTS:
                self._sleep(self._retry_backoff_seconds)
        raise last_error

    def search(self, query: str) -> list[SearchHit]:
        """Search Tavily and return hits."""
        try:
            response = cast(_TavilySearchResponse, self._client.search(query=query))
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
