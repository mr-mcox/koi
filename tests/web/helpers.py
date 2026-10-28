"""Builders and readers shared by the review-surface tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screen.api.app import AppState
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    upsert_company,
    upsert_opening,
)
from screen.types import (
    Assertion,
    Citation,
    Company,
    Fit,
    Opening,
    Target,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


def settled_compare_page(client: TestClient) -> httpx.Response:
    """`GET /compare` triggers a pre-screen pass in a `BackgroundTasks` callback; under
    `TestClient` the task finishes before this call returns, but the first response was
    already rendered from the pre-task state and shows the polling page. A second GET
    sees the finished `CompareProgress` and renders the real suggestion — the shape every
    `/compare`-reading test wants, not the transient status page."""
    first = client.get("/compare")
    assert first.status_code == 200
    if "compare-prescreening" not in first.text:
        return first
    return client.get("/compare")


def seed_opening(
    db_path: Path,
    *,
    company_id: str,
    opening_id: str,
    assertions: list[Assertion] | None = None,
    stage: str = "screening",
) -> None:
    conn = connect(db_path)
    upsert_company(conn, Company(id=company_id, name=f"{company_id} Inc", created_at=NOW))
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title=f"{opening_id} title",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            created_at=NOW,
            stage=stage,  # type: ignore[arg-type]
        ),
    )
    if assertions:
        append_assertions(conn, assertions, opening_id=opening_id)


def make_assertion(target: Target, fit: Fit) -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance="ratified",
        chunk="verbatim source text",
        citations=[CITATION],
        created_at=NOW,
    )


def boundary_glyph_positions(text: str) -> tuple[float, float, float]:
    """Return the rendered left position of the median marker plus the interval band's
    edges.
    Percentages are returned as fractions (0.0-1.0) in the order:
    median, low (range left edge), high (range right edge).
    """
    median_m = re.search(
        r'<span[^>]*class="[^"]*boundary-marker[^"]*boundary-median[^"]*"[^>]*style="[^"]*left:\s*([\d.]+)%',
        text,
    )
    range_m = re.search(
        r'<span[^>]*class="[^"]*boundary-range[^"]*"[^>]*style="[^"]*left:\s*([\d.]+)%;[^"]*right:\s*([\d.]+)%',
        text,
    )
    assert median_m is not None
    assert range_m is not None
    return (
        float(median_m.group(1)) / 100,
        float(range_m.group(1)) / 100,
        1 - float(range_m.group(2)) / 100,
    )


def live_state(client: TestClient) -> AppState:
    """The typed mutable state behind `client`'s app."""
    return cast(AppState, cast(FastAPI, client.app).state.live)
