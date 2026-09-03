"""Tests for the shared browser seam: screen.browser.

BrowserProtocol is the neutral contract. TavilyBrowser is the real
implementation; FakeTavily (in intake/fakes.py) is the test double used
throughout the intake test suite.
"""

from screen.browser import BrowserError, BrowserProtocol, SearchHit, TavilyBrowser
from screen.intake.fakes import FakeTavily


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
