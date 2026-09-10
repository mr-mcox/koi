---
feature: batch-intake
type: bearing
date: 2026-08-27
commit: b3f384156f944ac95f82f9b0577cf095c3faa0a8
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

`./run intake <url>` is one-at-a-time and foreground: queuing several openings means
waiting out each one, and a mid-pipeline failure leaves no record of which URL or why.
Web already covers rating/archive/research; intake is the last CLI-only surface.
Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] A URL submitted via a web form is durably queued (row in DB) before the response
      returns, surviving an immediate process crash → test inserts a row, reopens the DB
      connection, row is still `pending`
- [ ] A long-running worker processes queued URLs one at a time across many requests,
      not one bounded background task per submission → unit test drives it through two
      enqueue-while-processing cycles without restarting it
- [ ] A URL added mid-batch is picked up without restarting the worker → test enqueues a
      second URL during a fake first pipeline call, asserts it's processed too
- [ ] A failed URL records which stage failed and the error; the worker continues to the
      next pending URL → test: one fixture fails at fetch, one succeeds after it, both
      rows land with correct terminal status
- [ ] A page lists queue rows (pending/running/done/failed) with failure reasons shown →
      manual check + template test
- [ ] `intake/cli.py`'s Click command and `screen/__main__.py` are removed; `./run intake
      <url>` no longer exists → grep confirms no reference; `test_cli_group.py` updated

## Approach

- New `intake_queue` table (migration `0009_...sql`) + `store/repo.py` functions
  (enqueue, claim-next-pending, mark-done, mark-failed), following the existing
  migration+repo+mapper pattern rather than a new persistence layer (→ scouting F7).
- Extract today's Click-coupled pipeline (`_fetch_url` + `_identify_research_trace`) into
  a click-independent module, mirroring how `research/batch.py` was pulled out of
  `intake/cli.py` for the same reason (→ scouting F5, F8); it raises a plain exception
  carrying which stage failed, not `click.ClickException` (→ scouting F14).
- `POST /intake-queue` inserts one pending row synchronously in the request — queuing
  itself is blocking, per operator (→ scouting F11) — and takes a single URL, not a
  multi-URL paste box (→ scouting F15).
- A worker task started once in the FastAPI `lifespan` (not per-request
  `BackgroundTasks`, which is `BatchEngine`'s bounded-run shape, → scouting F5) claims
  and processes pending rows one at a time for the life of the process, re-querying after
  each item so a row inserted mid-run is picked up (→ scouting F13) without restarting.
- On failure, skip and continue to the next pending row; no retry (→ scouting F12).
- New page (e.g. `/intake-queue`) lists rows with status and failure reason, linked from
  the queue page's action row (→ scouting F10 — web is now the only intake surface).

## Not Doing

- Automatic retry, priority/reordering (FIFO only), and dedup of an already-queued or
  already-intaken URL — resubmitting just re-runs intake (upsert-idempotent already).
- Concurrent processing of multiple URLs — one at a time, matching today's one-pass model.

## Testing

Test-first by default. Exempt: nothing.

## Recalibrate When

- If claiming a row for the worker races with a request thread reading the same table
  (SQLite locking surfaces under real concurrency), stop and confirm the locking approach
  before proceeding rather than papering over it with a broad retry/except.
- If the lifespan-started worker needs to survive app reloads/multiple workers in a way
  that in-process state can't (mirrors `BatchEngine`'s single-worker assumption), stop —
  that's a bigger persistence question than this bearing scopes.

## Agreed

- Web-only, CLI retired; queuing (the write) is blocking/synchronous, processing runs in
  the background — operator: last CLI holdout, minimize risk of losing a submitted URL
  (→ scouting F10, F11)
- Failed URLs are skipped, not retried or blocking; a single "add one URL" form, not a
  multi-URL paste box — operator (→ scouting F12, F15)
- URLs may be appended while the worker is mid-run — operator, "open to discussion if it
  makes things complicated" (→ scouting F13); no complication surfaced, kept as stated
