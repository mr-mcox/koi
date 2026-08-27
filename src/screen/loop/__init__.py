"""Loop bounded-context package.

`loop/` is file-agnostic — it receives a LoopState, returns a PassSummary.
All file I/O lives in intake/cli.py.

Dependency rule: loop/ may import screen.types and screen.extract.
               intake/ may import loop/. Nothing in loop/ imports intake/.
"""
