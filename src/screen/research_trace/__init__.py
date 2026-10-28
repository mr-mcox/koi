"""Research trace: the append-only transcript of every tool call a research pass makes.

Shared substrate, not a bounded context. `intake/` writes the first events and
`research/` appends to them, so the trace cannot live in either without one
importing the other. Nothing here imports `intake/`, `research/`, `api/` or
`web/`; `tests/test_import_direction.py` enforces that.
"""
