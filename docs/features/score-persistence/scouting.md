---
feature: score-persistence
type: scouting
date: 2026-08-28
commit: 1c8ee938c8385cb728f2d790f15bfdfe9d680472
---

## What We're Doing

Operator's framing: before building a UI, get scoring persisted and servable — a command
that turns each opening's collected assertions into a stored score, assembled into a ranked
queue across companies, addressable by something outside the process. This is deliberately
*not* the review-ux feature (docs/features/review-ux/scouting.md) — that's next, gated on
this existing so there's an interface for a `Ruling` to write into. Persistence precedes UI.

## Findings

- **F1** — `src/screen/score/scorer.py`, `loader.py`, `types.py`, `band.py` — the pure
  Scorer is implemented and tested against real seed data (`tests/test_scorer.py`,
  `test_score_loader.py`, `test_band.py`): `score()` takes `(assertions, ScoringConfig) →
  ScoreResult`; `load_scoring_config()` reads `rubric.yaml`/`scoring.yaml`. This math is
  settled ground for this feature — not open for relitigation (domain-model.md Scorer
  section, decisions.md S1–S8).
- **F2** — `src/screen/intake/cli.py` — nothing in `src/` calls `score()`. The only command
  is `intake` (fetch → identify → extract → dispatch research). There is no code path from
  an opening's `assertions.jsonl` to a `ScoreResult`, and no assembly across openings/
  companies into a queue.
- **F3** — `data/<company>/openings/<id>/` — the only on-disk artifacts past intake are
  `company.json`, `opening.json`, `assertions.jsonl`, `transcript.jsonl`. No `score.json`,
  no queue file, nothing persisted from a scoring run.
- **F4** — `src/screen/types.py:69-95` — `Assertion` has no `id` field. Nothing outside its
  own file (by position in `assertions.jsonl`) can address "this specific assertion."
  domain-model.md's `Ruling` section and review-ux F6/F18 both need to reference one; this
  is a real gap the review-ux feature will hit regardless of what this feature does.
- **F5** — domain-model.md §Steel thread, "Then:" — the roadmap after the steel thread
  reads: "a few one-offs beginning-to-end → **batch several and inspect the ranking** →
  routing and the Inbox → PrecedentLookup → intake adapters → holding-area view." Persisting
  scores and assembling a ranked queue across companies is this exact next step, ahead of
  review-ux/routing.
- **F6** — `docs/architecture/prototype-decisions.md` D1 — the prototype was "local web app,
  SQLite-backed." decisions.md explicitly did not re-adopt this: "prototype mechanics; the
  clean build re-decides its own stack." Storage format and any serving layer are open
  space here, not a rediscovery of D1.
- **F7** — `src/screen/__main__.py`, `src/screen/intake/cli.py:124` — `intake` is a single
  `click.Command`, not a `click.Group`; `python -m screen <url>` calls it directly. Adding a
  second command (e.g. `score`) needs the entry point restructured into a group — a small,
  reversible CLI wiring change.
- **F8** — `src/screen/score/loader.py:1-3` — loader is explicitly "the only place in
  `screen.score` that touches the filesystem — `scorer.py` stays pure (no I/O)." A
  persistence step (reading `assertions.jsonl`, writing a score artifact) belongs in a new
  module/CLI layer, not inside `scorer.py` or `loader.py` — consistent with the existing
  intake/score package split.
- **F9** [x] — was open, closed by operator → **UUID, not content-hash**, for
  `Assertion.id`. Breaks precedent with `opening_id`/`transcript_id` (both truncated
  SHA-1 of stable inputs) deliberately: collision is a non-issue at this scale, and a
  random id is simpler than picking a stable-content basis to hash. Consequence accepted:
  re-running `intake` against an unchanged page creates new assertion rows rather than
  deduplicating (→ §Agreed).
- **F10** — `src/screen/types.py:14, 22` — `Company`/`Opening` are `frozen=True`,
  `extra="forbid"`. `Assertion` is the same. Adding a field to `Assertion` (an `id`) is a
  schema change to a frozen model that `tests/test_types.py` and `tests/test_scorer.py`
  construct directly in many places — every test constructing an `Assertion` literal breaks
  until updated. Mechanical, not risky, but real blast radius (grep shows the helper
  `_assertion()`/`_citation()` factories in `tests/test_scorer.py` and `tests/test_types.py`
  centralize construction, limiting the actual edit surface to those factories plus
  call sites that inline-construct).
- **F11** — `docs/architecture/README.md` — girders relevant here: "Fit and provenance are
  separate axes, always" and the closed `Target` Literal (Wall 3, `types.py:69-95`). Neither
  is touched by persisting a `ScoreResult` or adding an `Assertion.id` — the id is an
  identity field, not a scoring field, so Wall 1/2 (`extra="forbid"` guards against scoring
  fields) is not in tension.
- **F12** — `rubric.yaml`, `scoring.yaml` are read fresh per `load_scoring_config()` call —
  no caching, no versioning of which config produced a stored score. A persisted score
  artifact that outlives a `bar`/weight change (both named volatile in domain-model.md) will
  read as scored-under-old-config with nothing recording which config that was, unless the
  artifact captures rubric/scoring provenance itself.
- **F13** [x] — was open, closed by operator → **SQLite, not flat files**, for persisted
  domain data: schema enforcement plus a real migration path outweighs the flat-file
  precedent, given migrations are foreseeably near (→ §Agreed).
- **F14** [x] — was open, closed by operator → queue assembly happens at **read time**,
  computed from stored assertions/scores on each request, not written as a standing
  artifact. Avoids a recompute-on-write side-effect path entirely — the query does the
  assembling (→ §Agreed).
- **F15** — operator — this feature is scoped to persistence + a queue interface only.
  Review-ux (dimension-level `Ruling`, rating-VOI, transcript-computed research state,
  precedent flywheel) is explicitly deferred to the next feature, which this one's
  interface is meant to unblock. A UI itself is the feature after that.
- **F16** — operator — API layer should be FastAPI ("light and easy"), not a bare file
  interface. `intake` stays CLI-triggered for now; the operator anticipates a POST-to-trigger
  endpoint from a future frontend, but that trigger endpoint itself is not asked for by this
  feature — only that the persistence/API layer this feature builds doesn't foreclose it.
- **F17** — operator — `Assertion.id` is in scope for this feature (reversing the earlier
  lean to defer it to review-ux). Rationale: a queue needs stable identity to link back to
  source assertions regardless of Ruling; better to absorb the frozen-model blast radius
  (F10) once.
- **F18** [x] — was open, closed by operator → **broad DB boundary**: `Company`, `Opening`,
  `Assertion`, and the new score/queue projection all move into SQLite now. `transcript.jsonl`
  stays file-based as an append-only replay log (F8, F9); no split-brain between domain data
  and scoring data (→ §Agreed).
- **F19** [x] — was open, closed by operator → **directory structure is dropped
  entirely.** `data/<company_id>/openings/<id>/` (company.json, opening.json,
  assertions.jsonl) goes away once those three are DB rows; no migration of existing
  on-disk data is needed — the operator re-runs `intake` to repopulate. `transcript.jsonl`
  remains the one flat-file artifact, relocated to `data/transcripts/<transcript_id>.jsonl`
  (→ §Agreed).

## Not Yet Settled (carried into bearing discussion)

- F19 — closed, see above.
- Whether `score`/queue computation is exposed only via FastAPI routes, or also via a CLI
  command — closed: **FastAPI only.** A CLI command would be a second entry point into
  the same read logic for no requirement this feature has; `intake` already covers the
  CLI's actual job (writing data).
- ORM/migration tooling choice — closed: **no ORM.** Raw `sqlite3` + hand-written
  `to_row()`/`from_row()` mappers per model + a small numbered-`.sql`-file migration
  runner. Rejected SQLModel/SQLAlchemy ORM: `screen.types` is already the domain model
  (Wall 1/2/3 tested against it); an ORM model would double as the persistence model too,
  coupling domain shape to table shape, and tends to pull endpoints toward table shape
  rather than the domain question being asked. Trigger for revisiting recorded at
  `docs/architecture/open-questions.md` #15.
