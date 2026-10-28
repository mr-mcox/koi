"""Research bounded-context package.

`research/` is file-agnostic — it receives a LoopState, returns a PassSummary.
All file I/O lives in intake/cli.py.

Dependency rule: intake/ may import research/; nothing in research/ imports intake/.
"""
