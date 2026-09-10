"""Characterizes that the intake pipeline shares its dispatch/fetch mechanics
with `screen.research.batch` instead of duplicating them — the CLI-retirement
extraction copy-pasted `run_dispatch`, `read_page_content`, and the `build_*`
factories into `intake/pipeline.py`; this pins the target shape (re-export,
not a second implementation) before the dedup refactor."""

from __future__ import annotations

from screen.intake import pipeline
from screen.research import batch


def test_pipeline_run_dispatch_is_the_shared_batch_implementation() -> None:
    assert pipeline.run_dispatch is batch.run_dispatch


def test_pipeline_read_page_content_is_the_shared_batch_implementation() -> None:
    assert pipeline.read_page_content is batch.read_page_content


def test_pipeline_research_trace_path_for_is_the_shared_batch_implementation() -> None:
    assert pipeline.research_trace_path_for is batch.research_trace_path_for


def test_pipeline_build_factories_are_the_shared_batch_implementations() -> None:
    assert pipeline.build_client is batch.build_client
    assert pipeline.build_extractor is batch.build_extractor
    assert pipeline.build_digester is batch.build_digester
    assert pipeline.build_planner is batch.build_planner
