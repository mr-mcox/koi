---
feature: research-batch-web-trigger
type: bearing
date: 2026-09-04
commit: eb492bb
branch: resumable-research
status: implementing
scouting: ./scouting.md
---

## Problem

`research-batch`/`bump-research-turns-budget`/`research`/`research-status` are CLI-only.
The operator wants to trigger a research batch and watch its progress from the queue
page, and to drop CLI support for everything research-related that the UI now
supersedes. Terrain: [scouting.md](./scouting.md).

## Done When

- [ ] The queue page has a control that starts a research batch with an operator-chosen
      `batch_size` and returns immediately — test: `POST` returns before the batch's
      turns are spent (route test with a slow fake planner/browser + a gate the test
      releases after asserting the response landed)
- [ ] While a batch runs, the queue page reflects turns spent/remaining for that run, and
      the opening currently being worked if that's cheap to expose — test: polling the
      status during a paused fake-planner run shows in-progress state, not just
      before/after (→ operator F16)
- [ ] Each queue item shows that opening's research turns used vs. its budget —
      supersedes `research-status`'s CLI output (→ scouting F24 [research_status precedent], operator F17)
- [ ] A second batch-start request while one is running is rejected with a clear message,
      not double-run or silently queued — test: two rapid `POST`s, only one batch's
      turns get spent
- [ ] `research`, `research-batch`, `bump-research-turns-budget`, `research-status`
      CLI commands and their test files are gone; `intake`, `backfill-digests`,
      `backfill-research-turns-budget`, `backfill-dimension-ruling-covered-assertion-ids`
      remain — test: `grep -n "add_command" src/screen/intake/cli.py` lists only the four
      survivors (→ operator F17)
- [ ] Existing queue/rating/digest web tests and API tests pass unmodified

## Approach

- Extract the batch loop, `_resume_opening`, and their weight-computation helpers out of
  `intake/cli.py` into a new `screen/research/batch.py`, click-independent — the web route
  and the gutted CLI (nothing left to call it, post-removal) don't duplicate dispatch
  wiring (→ scouting F3)
- New `POST` route on `web/routes.py` (not `api/routes.py` — JSON API stays read-only per
  its module docstring) schedules the batch via `fastapi.BackgroundTasks`, opening its own
  `Database.connect()` rather than the per-request `Conn` dependency, since the task
  outlives the request (→ scouting F9, F10)
- Progress lives in an in-memory dict on `app.state` (current batch's total/spent/current-
  opening-id), not persisted — single-`uvicorn`-worker assumption, mirrors the bandit's
  own stdout-trace-not-a-table precedent (→ scouting F6, open-questions.md #15)
- Queue page polls a small status partial (`hx-trigger="every Ns"`) while a batch is
  running — new interaction vocabulary, no existing polling precedent to reuse (→
  scouting F8, operator F16)
- Per-opening turns-used/budget on the queue reads the same `_remaining_budget`/replay
  logic `_eligible_weights` already computes — no new computation, just rendering it (→
  scouting F3)

## Not Doing

- Persisted batch-run history — status resets on process restart, same as today's
  stdout-only trace (→ scouting F6, open-questions #15)
- Queuing multiple batch requests — single in-flight guard only, no queue
- A web control for the per-opening `research_turns_budget` cap — only `batch_size` is
  exposed (→ operator F14)
- A 1:1 web replacement for the singular `research <opening-id> <turns>` resume — deleted
  outright, not mirrored (→ operator F17)
- Multi-worker concurrency for the in-memory batch status — single-worker assumed (→
  scouting F6)

## Testing

Test-first by default. Exempt: nothing named at this level.

## Recalibrate When

- `./run serve` ever gains `--workers` > 1 — the in-memory single-process status breaks
- The polling interval or "currently working on" detail turns out to be noise or too
  laggy to be worth showing — simplify to spent/remaining counts only
- The operator repeatedly wants to queue a second batch rather than being blocked — revisit
  the single-in-flight guard

## Agreed

- Only `batch_size` is a web control; the per-opening budget bump gets no UI here (→
  operator F14)
- Queue page hosts the trigger — another entry point into the queue, not a new page (→
  operator F15)
- Progress shows turns spent/remaining and, if cheap, the opening currently being worked
  (→ operator F16)
- `research`, `research-batch`, `bump-research-turns-budget`, `research-status` CLI
  commands are removed outright; only `intake` and the three `backfill-*` migration
  commands remain (→ operator F17)
