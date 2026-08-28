---
feature: score-persistence
type: bearing
date: 2026-08-28
commit: 1c8ee938c8385cb728f2d790f15bfdfe9d680472
branch: scorer
status: done
scouting: ./scouting.md
---

## Problem

The pure Scorer exists but nothing persists its input or output, and nothing serves a
ranked view across companies. Before building review UX or a UI, this feature gives both an
addressable home: domain data in a real schema (migrations are foreseeably near), a queue
computable across companies, and stable assertion identity for a future `Ruling` to target.
Terrain: [scouting.md](./scouting.md). **Precedes, and is a prerequisite for, the review-ux
UI** — that is the next feature after this one, not folded in here.

## Done When

- [x] `Company`, `Opening`, `Assertion` are SQLite-backed (via a hand-written numbered-`.sql`
      migration, not an ad hoc `CREATE TABLE`) and round-trip through the existing intake
      pipeline → a test that runs `intake`'s pipeline against a fake browser/extractor and
      reads the rows back
- [x] `Assertion` carries a stable `id` (UUID) →
      `tests/test_types.py`, every constructed `Assertion` has an `id`
- [x] A FastAPI endpoint returns one opening's `ScoreResult` (standing/reach/band),
      computed at request time from its DB-stored assertions and current
      `rubric.yaml`/`scoring.yaml` → integration test via `TestClient`
- [x] A FastAPI endpoint returns a ranked queue across all companies/openings in the DB,
      assembled at request time (no stored queue row) → same, asserting sort order
      matches direct `score()` calls on the same fixture data
- [x] `uv run python scripts/check.py` passes with the new modules included in coverage

## Approach

- SQLite is the single store for `Company`/`Opening`/`Assertion`; no `ScoreResult` or
  queue row is ever persisted — both are recomputed from stored assertions + whatever
  `rubric.yaml`/`scoring.yaml` say *now* on every read (→ scouting F13, F14, F12 — this
  also means a `bar`/weight change can never leave a stale stored score behind)
- No `data/<company_id>/openings/<id>/` directory structure survives — `company.json`,
  `opening.json`, `assertions.jsonl` are retired now that those three are DB rows; no
  migration of existing on-disk data is done, the operator re-runs `intake` to repopulate
  (→ scouting F19). `transcript.jsonl` stays file-based, append-only, unchanged in shape;
  relocates to `data/transcripts/<transcript_id>.jsonl`, addressed via
  `Opening.transcript_id`
- FastAPI serves read-only endpoints only (opening score, queue); `intake` stays a CLI
  command this feature — a future trigger endpoint is anticipated but not built
  (→ scouting F16)
- No ORM: raw `sqlite3` + hand-written `to_row()`/`from_row()` mapper functions per model,
  plus a small numbered-`.sql`-file migration runner. `screen.types` stays the one and only
  domain model (Wall 1/2/3 tested against it); an ORM would double it as the persistence
  model too, coupling domain shape to table shape and pulling endpoints toward table shape
  rather than the domain question being asked. Trigger for revisiting recorded at
  `docs/architecture/open-questions.md` #15.
- `Assertion.id` is a UUID, not content-derived — breaks precedent with `opening_id`/
  `transcript_id` (both content-hashed) deliberately; collision is a non-issue at this
  scale and UUID is simpler (→ scouting F9)

## Resolved (were Deferred during implementation)

- `store/repo.py`'s flat functions stay flat, not methods on a client/`Store` object —
  resolved at the FastAPI cycle: `Database` (in `screen/api/app.py`) is the connection-
  lifecycle seam (open/close, foreign keys, migrations); `repo.py` stays a module of SQL
  operations taking `conn` as an argument. Repo functions don't hold state a method would
  need, and the SQL itself is already SQLite-specific either way — the connection seam is
  what actually matters for a future hosted/pooled backend, not the repo's function-vs-
  method shape.
- `tests/test_cli.py` (560 lines) split into `tests/cli/`: `test_smoke.py`,
  `test_pipeline.py` (CliRunner end-to-end), `test_identify_transcript.py`,
  `test_extract_assertions.py`, plus a shared `helpers.py`.

## Not Doing

- Any dimension-level `Ruling` object, rating-VOI, or transcript-computed research state
  — review-ux's scope entirely, deferred until this feature's interface exists for it to
  write into
- A POST/trigger endpoint that runs `intake` from the API — anticipated, not built
  (→ scouting F16)
- A CLI command for score/queue computation — FastAPI is the only read surface; a second
  entry point into the same logic isn't needed
- Any actual UI screen — this feature's endpoints are what a UI consumes next; building
  that UI is the immediate next feature after this one and after review-ux, not this one
- Migrating the operator's real, gitignored `data/` contents — fixtures and tests use
  synthetic data only, per the repo's privacy rules

## Testing

Test-first by default. Exempt:
- none named yet — flag during implementation if the FastAPI app's process entrypoint
  needs the same live-network-style exemption `browser.py`/`baml_extractor.py` carry

## Recalibrate When

- If `Company`/`Opening`/`Assertion` can't map cleanly to rows with hand-written
  `to_row()`/`from_row()` functions without real duplication of validation logic already
  in `screen.types`, stop — that's evidence the no-ORM call needs revisiting sooner than
  open-questions.md #15's stated trigger.

## Agreed

- SQLite over flat files, not a narrower "just Assertion" cut — schema enforcement and
  migrations outweigh the flat-file precedent; broad boundary (Company, Opening, Assertion
  all move together) avoids a split-brain between domain data and scoring data
  (→ scouting F13, F18)
- Queue and per-opening score are computed at read time, never stored — avoids a
  recompute-on-write side effect path (→ scouting F14)
- `Assertion.id` is in scope for this feature, not deferred to review-ux — a queue needs
  stable identity regardless of Ruling (→ scouting F17)
- `Assertion.id` is a UUID, not a content-hash — reverses the F9 lean toward
  hash-derived ids; simplicity wins since collision risk is moot at this scale (→
  scouting F9)
- `data/<company_id>/openings/<id>/` directory structure is dropped, not reorganized —
  no migration path needed, the operator re-runs `intake` (→ scouting F19)
- FastAPI is the only read surface for score/queue; no parallel CLI command
- No ORM — raw `sqlite3` + hand-written mappers + numbered-`.sql` migrations; trigger for
  reconsidering recorded at `docs/architecture/open-questions.md` #15
