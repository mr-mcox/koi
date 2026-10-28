"""Characterizes that the intake pipeline shares its dispatch and trace mechanics
with the modules that own them instead of duplicating them — the CLI-retirement
extraction copy-pasted `run_dispatch`, `read_page_content`, and the `build_*`
factories into `intake/pipeline.py`; this pins the shared implementation."""

from screen.intake import pipeline
from screen.research import batch
from screen.research_trace import trace_io


def test_pipeline_run_dispatch_is_the_shared_batch_implementation() -> None:
    assert pipeline.run_dispatch is batch.run_dispatch


def test_pipeline_read_page_content_is_the_shared_trace_implementation() -> None:
    assert pipeline.read_page_content is trace_io.read_page_content


def test_pipeline_research_trace_path_for_is_the_shared_trace_implementation() -> None:
    assert pipeline.research_trace_path_for is trace_io.research_trace_path_for
