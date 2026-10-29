"""Tests for the shared browser seam: screen.browser.

TavilyBrowser is the real implementation of `Browser`; these tests drive it
through its `client` seam.
"""

from typing import Any

from screen.browser import BrowserError, TavilyBrowser, failures_are_permanent


def _no_sleep(_seconds: float) -> None:
    """Collapses the retry backoff so tests don't pay it."""


class _SpyTavilyClient:
    """Stand-in for the Tavily SDK client, injected via TavilyBrowser's
    `client` seam so tests exercise real dispatch logic without network I/O."""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        search_response: dict[str, Any] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._search_response = search_response or {"results": []}
        self.extract_calls: list[dict[str, Any]] = []

    def extract(self, **kwargs: Any) -> dict[str, Any]:
        self.extract_calls.append(kwargs)
        return self._responses.pop(0)

    def search(self, **_kwargs: Any) -> dict[str, Any]:
        return self._search_response


class _RaisingTavilyClient:
    """Tavily SDK stand-in whose every call raises, as the SDK does on a network
    or auth failure."""

    def __init__(self) -> None:
        self.extract_calls = 0

    def extract(self, **_kwargs: Any) -> dict[str, Any]:
        self.extract_calls += 1
        raise RuntimeError("connection reset")

    def search(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("connection reset")


def test_browser_error_details_default_to_empty_dict() -> None:
    """BrowserError constructed without `details` exposes an empty dict, not None,
    so callers can always write `exc.details` into a trace event."""
    exc = BrowserError("boom")
    assert exc.details == {}


def test_browser_error_carries_details() -> None:
    """details holds whatever raw failure info the transport gave us, for the
    caller to record verbatim in the trace (no classification here)."""
    exc = BrowserError(
        "fetch failed", details={"failed_results": [{"error": "Failed to fetch url"}]}
    )
    assert exc.details == {"failed_results": [{"error": "Failed to fetch url"}]}


def test_tavily_browser_fetch_uses_advanced_depth() -> None:
    """basic-depth extraction fails outright or returns thin boilerplate on
    JS-rendered ATS pages (Workday, AshbyHQ, Indeed, LinkedIn) — observed
    across 16 of 18 live intake failures. advanced is the fix; this pins it
    so a future refactor can't silently drop back to the default."""
    spy = _SpyTavilyClient(
        responses=[{"results": [{"url": "https://example.com/job/1"}], "failed_results": []}]
    )
    client = TavilyBrowser(api_key="x", client=spy)
    client.fetch("https://example.com/job/1")
    assert spy.extract_calls[0]["extract_depth"] == "advanced"


def test_tavily_browser_fetch_retries_once_on_failure() -> None:
    """A fetch failing on the first attempt and succeeding on an identical
    retry is a real, observed pattern (transient timeouts against ATS
    pages) — not a hidden failure being papered over."""
    spy = _SpyTavilyClient(
        responses=[
            {
                "results": [],
                "failed_results": [
                    {"url": "https://example.com/job/1", "error": "Failed to fetch url"}
                ],
            },
            {
                "results": [{"url": "https://example.com/job/1", "raw_content": "ok"}],
                "failed_results": [],
            },
        ]
    )
    client = TavilyBrowser(api_key="x", client=spy, sleep=_no_sleep)
    hit = client.fetch("https://example.com/job/1")
    assert hit["raw_content"] == "ok"
    assert len(spy.extract_calls) == 2


def test_tavily_browser_fetch_raises_after_max_attempts() -> None:
    """A persistent but unclassifiable failure exhausts both attempts and
    still raises — retrying doesn't mask it."""
    fail_response = {
        "results": [],
        "failed_results": [{"url": "https://example.com/job/1", "error": "Failed to fetch url"}],
    }
    spy = _SpyTavilyClient(responses=[dict(fail_response), dict(fail_response)])
    client = TavilyBrowser(api_key="x", client=spy, sleep=_no_sleep)
    raised = False
    try:
        client.fetch("https://example.com/job/1")
    except BrowserError:
        raised = True
    assert raised
    assert len(spy.extract_calls) == 2


def test_tavily_browser_fetch_does_not_retry_a_404() -> None:
    """A 404 spends one call, not two — retrying a dead link can't help."""
    spy = _SpyTavilyClient(
        responses=[
            {
                "results": [],
                "failed_results": [
                    {"url": "https://example.com/job/1", "error": "404 page not found"}
                ],
            }
        ]
    )
    client = TavilyBrowser(api_key="x", client=spy, sleep=_no_sleep)
    try:
        client.fetch("https://example.com/job/1")
        raise AssertionError("expected BrowserError")
    except BrowserError as exc:
        assert exc.permanent
    assert len(spy.extract_calls) == 1


def test_tavily_browser_fetch_backs_off_between_attempts() -> None:
    """The retry waits before trying again — the failures it recovers from
    arrive in bursts, so an immediate retry would sample the same bad window.
    """
    fail_response = {
        "results": [],
        "failed_results": [{"url": "https://example.com/job/1", "error": "Failed to fetch url"}],
    }
    spy = _SpyTavilyClient(responses=[dict(fail_response), dict(fail_response)])
    slept: list[float] = []
    client = TavilyBrowser(api_key="x", client=spy, retry_backoff_seconds=1.5, sleep=slept.append)
    try:
        client.fetch("https://example.com/job/1")
    except BrowserError:
        pass
    assert slept == [1.5]


def test_failures_are_permanent_requires_every_failure_to_be_permanent() -> None:
    """One unrecognized error among the failures keeps the fetch retryable."""
    assert not failures_are_permanent(
        [{"error": "404 page not found"}, {"error": "Failed to fetch url"}]
    )


def test_failures_are_permanent_is_false_for_no_failures() -> None:
    """An empty failure list is not evidence of a dead link."""
    assert not failures_are_permanent([])


def test_tavily_browser_fetch_reports_an_empty_response_as_no_results() -> None:
    """A response with neither results nor failures still raises, after the retry."""
    empty = {"results": [], "failed_results": []}
    spy = _SpyTavilyClient(responses=[dict(empty), dict(empty)])
    client = TavilyBrowser(api_key="x", client=spy, sleep=_no_sleep)
    try:
        client.fetch("https://example.com/job/1")
        raise AssertionError("expected BrowserError")
    except BrowserError as exc:
        assert "no results" in str(exc)
        assert not exc.permanent
    assert len(spy.extract_calls) == 2


def test_tavily_browser_wraps_sdk_exceptions_and_retries_them() -> None:
    """An SDK exception surfaces as a retryable BrowserError carrying the exception
    text, so the caller records it in the trace instead of crashing the pass."""
    raising = _RaisingTavilyClient()
    client = TavilyBrowser(api_key="x", client=raising, sleep=_no_sleep)
    try:
        client.fetch("https://example.com/job/1")
        raise AssertionError("expected BrowserError")
    except BrowserError as exc:
        assert exc.details == {"exception": "connection reset"}
        assert not exc.permanent
    assert raising.extract_calls == 2


def test_tavily_browser_search_wraps_sdk_exceptions() -> None:
    client = TavilyBrowser(api_key="x", client=_RaisingTavilyClient())
    try:
        client.search("acme staff engineer")
        raise AssertionError("expected BrowserError")
    except BrowserError as exc:
        assert exc.details == {"exception": "connection reset"}


def test_tavily_browser_search_maps_content_to_raw_content_and_snippet() -> None:
    """Tavily search returns page text as `content`; the planner reads `raw_content`
    and `snippet`, so a hit without that mapping reaches it with no text at all."""
    spy = _SpyTavilyClient(
        search_response={
            "results": [
                {"url": "https://a.example/", "title": "A", "content": "Page text."},
                {"url": "https://b.example/"},
            ]
        }
    )
    hits = TavilyBrowser(api_key="x", client=spy).search("acme")
    assert hits == [
        {
            "url": "https://a.example/",
            "title": "A",
            "raw_content": "Page text.",
            "snippet": "Page text.",
        },
        {"url": "https://b.example/"},
    ]


def test_tavily_browser_search_prefers_raw_content_and_snippet_over_content() -> None:
    spy = _SpyTavilyClient(
        search_response={
            "results": [
                {
                    "url": "https://a.example/",
                    "raw_content": "Full page.",
                    "snippet": "Short.",
                    "content": "Summary.",
                }
            ]
        }
    )
    hits = TavilyBrowser(api_key="x", client=spy).search("acme")
    assert hits[0].get("raw_content") == "Full page."
    assert hits[0].get("snippet") == "Short."
