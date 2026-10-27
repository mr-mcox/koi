"""Tests for the shared browser seam: screen.browser.

BrowserProtocol is the neutral contract. TavilyBrowser is the real
implementation; FakeTavily (in intake/fakes.py) is the test double used
throughout the intake test suite.
"""

from typing import Any

from screen.browser import (
    BrowserError,
    BrowserProtocol,
    SearchHit,
    TavilyBrowser,
    failures_are_permanent,
)
from screen.intake.fakes import FakeTavily


def _no_sleep(_seconds: float) -> None:
    """Collapses the retry backoff so tests don't pay it."""


class _SpyTavilyClient:
    """Stand-in for the Tavily SDK client, injected via TavilyBrowser's
    `client` seam so tests exercise real dispatch logic without network I/O."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.extract_calls: list[dict[str, Any]] = []

    def extract(self, **kwargs: Any) -> dict[str, Any]:
        self.extract_calls.append(kwargs)
        return self._responses.pop(0)


def test_browser_protocol_is_runtime_checkable() -> None:
    """BrowserProtocol is decorated @runtime_checkable so isinstance works."""
    fake = FakeTavily()
    assert isinstance(fake, BrowserProtocol)


def test_tavily_browser_satisfies_protocol() -> None:
    """TavilyBrowser satisfies BrowserProtocol by shape — no real key needed."""
    client = TavilyBrowser(api_key="test-key-not-real")
    assert isinstance(client, BrowserProtocol)


def test_tavily_browser_has_no_extract_one() -> None:
    """extract_one was the old single-URL verb. fetch is its replacement;
    extract_one must not appear on TavilyBrowser."""
    client = TavilyBrowser(api_key="x")
    assert not hasattr(client, "extract_one")


def test_fake_tavily_satisfies_browser_protocol() -> None:
    """FakeTavily is the test double for BrowserProtocol callers."""
    fake = FakeTavily()
    assert isinstance(fake, BrowserProtocol)


def test_fake_tavily_has_no_extract_one() -> None:
    """FakeTavily's public surface matches BrowserProtocol — no extract_one."""
    fake = FakeTavily()
    assert not hasattr(fake, "extract_one")


def test_browser_error_is_exception() -> None:

    assert issubclass(BrowserError, Exception)


def test_search_hit_is_typed_dict() -> None:
    """SearchHit is a TypedDict; dict literals with the right keys satisfy it."""
    hit: SearchHit = {"url": "https://example.com/", "raw_content": "ok"}
    assert hit["url"] == "https://example.com/"


def test_fake_tavily_fetch_returns_hit() -> None:
    """fetch(url) is the single-URL verb replacing extract_one."""
    fake = FakeTavily(
        fixtures={
            "https://example.com/job/99": {
                "results": [
                    {
                        "url": "https://example.com/job/99",
                        "raw_content": "Synthetic posting.",
                    }
                ],
                "failed_results": [],
            }
        }
    )
    hit = fake.fetch("https://example.com/job/99")
    assert hit["url"] == "https://example.com/job/99"
    assert hit["raw_content"] == "Synthetic posting."


def test_fake_tavily_fetch_raises_on_unknown_url() -> None:
    """A URL with no fixture raises BrowserError."""
    fake = FakeTavily(fixtures={})
    raised = False
    try:
        fake.fetch("https://nowhere.example/missing")
    except BrowserError:
        raised = True
    assert raised


def test_fake_tavily_fetch_raises_on_empty_fixture() -> None:
    """A URL with an empty results list raises BrowserError."""
    fake = FakeTavily(
        fixtures={"https://example.com/jobs/42": {"results": [], "failed_results": []}}
    )
    raised = False
    try:
        fake.fetch("https://example.com/jobs/42")
    except BrowserError:
        raised = True
    assert raised


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


def test_fake_tavily_fetch_error_carries_failed_results_details() -> None:
    """FakeTavily.fetch's BrowserError.details exposes the failed_results entry,
    mirroring what TavilyBrowser would surface from a real Tavily failure."""
    fake = FakeTavily(fixtures={})
    try:
        fake.fetch("https://nowhere.example/missing")
        assert False, "expected BrowserError"
    except BrowserError as exc:
        assert "failed_results" in exc.details


def test_tavily_browser_extract_uses_advanced_depth() -> None:
    """basic-depth extraction fails outright or returns thin boilerplate on
    JS-rendered ATS pages (Workday, AshbyHQ, Indeed, LinkedIn) — observed
    across 16 of 18 live intake failures. advanced is the fix; this pins it
    so a future refactor can't silently drop back to the default."""
    spy = _SpyTavilyClient(responses=[{"results": [], "failed_results": []}])
    client = TavilyBrowser(api_key="x", client=spy)
    client.extract(["https://example.com/job/1"])
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
