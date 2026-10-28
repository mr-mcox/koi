"""Research bounded-context package.

`research/` is file-agnostic — it receives a LoopState, returns a PassSummary.
Trace file I/O lives in `screen/research_trace/`, which both this package and
`intake/` import.

Dependency rule: `intake/` may import `research/`; nothing in `research/` imports
`intake/`, `api/` or `web/`. Enforced by `tests/test_import_direction.py`.
"""
