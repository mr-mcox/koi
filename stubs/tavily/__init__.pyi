"""Type stubs for the third-party `tavily` package, which ships without
PEP 484 annotations. We declare only the surface `screen` actually
crosses — `TavilyClient.extract` returns our `TavilyResponse` shape.
The vendor surface (search, crawl, async client) is intentionally not
declared here; we never call it.
"""

from typing import Any


class TavilyClient:
    def __init__(self, api_key: str, **kwargs: Any) -> None: ...
    def extract(
        self,
        urls: list[str] | str,
        *,
        include_images: bool | None = None,
        extract_depth: str | None = None,
        format: str | None = None,
        timeout: float | None = None,
        include_favicon: bool | None = None,
        include_usage: bool | None = None,
        query: str | None = None,
        chunks_per_source: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...
