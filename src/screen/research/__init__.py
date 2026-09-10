"""Research bounded-context package.

`research/` is file-agnostic — it receives a LoopState, returns a PassSummary.
All file I/O lives in intake/cli.py.

Dependency rule: research/ may import screen.types and screen.extract.
               intake/ may import research/. Nothing in research/ imports intake/.
"""
