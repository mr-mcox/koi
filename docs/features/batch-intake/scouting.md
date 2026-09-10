---
feature: batch-intake
type: scouting
date: 2026-08-27
commit: b3f384156f944ac95f82f9b0577cf095c3faa0a8
---

## What We're Doing

Operator: running `./run intake <url>` one at a time is friction — you wait for one to
finish before starting the next, and when one fails partway through you don't remember
which URL it was. Wants a way to queue up a batch of URLs (and add more to an
already-queued batch), have them run without babysitting each one, and see which ones
failed and why.

## Findings

- **F1** — `src/screen/intake/cli.py:144-149` — `intake` is a Click command taking one
  `url` argument. It calls `_fetch_url` (Tavily extract → research trace) then
  `_identify_research_trace` (identify → persist Company/Opening → extract assertions →
  run one research-dispatch pass → warm digests). All synchronous, one process, one URL.
- **F2** — `src/screen/intake/cli.py:218-235` (`_fetch_url`) — on `BrowserError` (the
  Tavily fetch failing), it records a partial research trace event, then raises
  `click.ClickException`, which exits the process non-zero. Nothing downstream of that
  point (identify, persist, extract, dispatch) can fail *and* leave a record — those
  raise straight through with no equivalent recording.
- **F3** — `src/screen/paths.py` — `SCREEN_DATA_DIR` selects the data root; `./run`
  hardcodes it to `data/live/` for the operator, tests/manual runs default to `./data`.
  Any queue persistence must live under this same root to follow the existing
  single-data-root convention.
- **F4** — `./run:16-19` — `./run intake <url>` is the only user-facing entry point;
  `exec uv run python -m screen "$@"` → `screen/__main__.py` → `intake.main(...)`,
  Click's `standalone_mode=True` (exits process on completion/error). No notion of
  "run in background" or "process several" exists anywhere in the CLI surface.
- **F5** — `src/screen/research/batch.py:588-621` (`BatchEngine`) — a precedent for
  "run several units of async-ish work, track progress, tolerate a long-running call":
  the *research* batch (spending turns on already-intaked openings) runs via
  `fastapi.BackgroundTasks` in the web process, progress kept in an **in-memory dict**
  (`app.state.batch_status`, `BatchProgress`) — explicitly "not persisted" (batch.py:317
  docstring) and lost on process restart. This is a *different* pipeline stage than
  intake (F1): batch resumes existing Openings against their research budget; intake
  turns a raw URL into a Company+Opening in the first place. No code path currently
  chains "intake a fresh URL" into the web batch engine.
- **F6** — operator — wants failures to survive being *forgotten*, i.e. across whatever
  gap exists between submitting a batch and coming back to check on it — not just
  surfaced in the terminal that happened to be running it. This is stronger than
  `BatchEngine`'s in-memory progress dict (F5): it implies the queue and its per-item
  outcomes need to persist across process restarts, which an in-memory dict does not
  survive.
- **F7** — `src/screen/store/migrations/` — the existing persistence pattern for new
  durable state is a numbered `.sql` migration (0001-0008) plus a `store/repo.py`
  function per operation, mapped through `store/mappers.py` to a `screen.types` model.
  A durable intake queue would follow this same shape: new table, new repo functions,
  no new persistence technology (→ open-questions §15, ORM not earning its keep yet).
- **F8** — `src/screen/intake/cli.py:34-38`, `44-48` — `_build_client`/`_build_identifier`
  etc. are already factory functions taking no args, swappable via `monkeypatch` in
  `tests/cli/helpers.py` (`patch_extractor`, `patch_planner`, `patch_digester`) — the
  existing seam a queue-runner would reuse rather than re-deriving DI for the pipeline.
- **F9** — decisions.md, domain-model.md — no wall or decision speaks to intake
  concurrency or ordering; queuing/sequencing is open space. `open-questions.md #10`
  ("lightweight vs heavy screening at intake") is about pre-screening cost, not batching
  mechanics — doesn't bind this either.
- **F10** [x] — web surface, CLI retired — operator: "Intake is the only holdout where
  I cannot do via web. We can retire CLI." → §Approach, §Not Doing.
- **F11** [x] — background daemon that keeps working, but *queuing* (adding URLs to the
  DB) is blocking/synchronous so queued work is never only-in-memory — operator: "queuing
  up all of the intaked urls should be blocking so that likelihood of lost work is low"
  → §Approach (durable queue table, background worker processes it).
- **F12** [x] — skip and continue; failed URL is recorded with its reason, queue moves on
  — operator → §Done When, §Approach.
- **F13** [x] — appended mid-run: a URL can be added to the queue while the worker is
  processing it — operator, with "open to discussion if it makes things complicated" →
  §Approach (worker re-queries pending rows rather than snapshotting the queue once).
- **F15** — operator: open to a single "add one URL to the queue" submit form rather than
  a multi-URL paste box, if it keeps the feature simpler → §Approach.
- **F14** — `src/screen/intake/cli.py:96, 111` and `234` — every existing intake failure
  path raises an exception type (`click.ClickException`) that is fine for a single
  foreground command (message + non-zero exit) but wrong for a queue runner that must
  catch it, record which URL and which stage failed, and continue to the next item —
  none of today's raise sites carry a stage label or return a structured error.
