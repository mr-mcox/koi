---
feature: dimension-digest
type: scouting
date: 2026-08-29
commit: 4ed61f7
---

## What We're Doing

Split out of `review-ux` (F33 there): the rating view's assertion list is too much raw
text to scan. Operator wants, per dimension, a scannable one-line-or-two digest of the
evidence's overall *vibe* — not a count, not a verdict, not a Fit label — with the
underlying assertions still one click away. New feature because it isn't necessarily
`review-ux`'s child: it touches extraction/generation as much as display.

Operator's explicit style guidance (this session): reject anything that describes its own
existence ("there are three assertions and they show a mix" is a wasted sentence). The
digest should read as a human summarizing what the evidence actually says, e.g. testing
against a real seed opening's assertions (not one of the `prototype-decisions.md`
Company A–D pseudonyms — this is clean-build seed data, name withheld separately):

- `internal_culture` (Strong, 1 assertion): "High-intensity, high-bar culture — explicit
  'not a place for complacency' framing, no signal of forced-ranking or layoff churn."
- `location` (Mixed, 1 assertion): "Remote-first in name, but with a real catch — the
  same posting welcomes remote hires nationally and then disqualifies this location."
- `mission` (Mixed, 1 assertion): "Mission language aims at 'economic freedom for a
  billion people'; the actual scope is compliance-automation tooling — inspiring frame,
  narrower work."

The source assertions used to draft these live in a gitignored `data/` subdirectory
(never committed per the privacy boundary — real company names, real evidence quotes).

## Findings

- **F1** — `src/screen/web/templates/rating.html:11-20` — assertions render as one flat
  `<ul>` in whatever order `assertions_for_opening` returns them (insertion/file order),
  no grouping, no per-dimension rollup shown alongside the raw list.
- **F2** [x] — domain-model.md §Ruling, `review-ux/scouting.md` F6/F18 — a dimension-level
  **Ruling** ("given all the underlying assertions & rulings, what's the overall
  disposition for this dimension") was already identified as a distinct, undecided object.
  Operator closed the ambiguity: a dimension-level Ruling is **operator-origin** (their
  disposition) and is not what's being asked for here — this feature is a separate,
  **LLM-generated**, non-judgment gist. → bearing.md.
- **F3** — `src/screen/score/scorer.py:57-64` (`_target_stats`) — a per-target
  `mean`/`half_width`/`n` is already computed for every scoring/constraint target as an
  intermediate value inside `score()`, then discarded. The numeric raw material for "what
  does the evidence say about this dimension, in aggregate" already exists inside the
  Scorer; nothing surfaces it as an API/template value today. Not needed for the digest
  itself (F2 — this is prose, not a number) but may be useful for later ordering/triage.
- **F4** — decisions S6/S7, domain-model wall 4 — any per-dimension summary shown to the
  operator must stay qualitative, never a number ("precision ranks, bands display").
  Consistent with F2/the operator's own framing — the digest is prose, never a score.
- **F5** — operator, this session — pushback on computing the digest on every page read:
  an LLM call every view is priced per view, not per change, and gets expensive. Wants
  staleness noted when the underlying assertions change, recompute only then.
- **F6** — `src/screen/store/repo.py:43-49` (`append_assertions`) — assertions are strictly
  append-only (wall 6; no `UPDATE`/`DELETE` path exists in `repo.py` at all). Consequence:
  "has this dimension's evidence changed since the digest was computed" reduces to a
  single cheap comparison — the *count* of assertions currently filed against a target vs.
  the count the cached digest was computed over. No hashing, no diffing needed;
  append-only makes monotonic count comparison exact and sufficient.
- **F7** — `src/screen/store/migrations/0001_create_domain_tables.sql` — no existing table
  fits a cached digest; a new table is required (e.g. `dimension_digests(opening_id,
  target, digest, assertion_count, computed_at)`, keyed `(opening_id, target)`). Additive
  migration, no change to `assertions`/`openings`/`companies`.
- **F8** — `src/screen/extract/protocol.py`, `src/screen/extract/baml_extractor.py` — the
  existing `ExtractorProtocol` + `BAMLExtractor` + `FakeExtractor` shape (a Protocol the
  live BAML adapter and a test fake both satisfy) is the established pattern for adding a
  new LLM-backed capability without coupling call sites to BAML directly — the digest
  generator should mirror this shape, not invent a new one.
- **F9** — `scripts/check.py` `OMIT_FROM_COVERAGE` — `src/screen/extract/baml_extractor.py`
  is explicitly exempted from coverage ("live BAML adapter: calls external LLM service, no
  unit test coverage by design"). A live digest-generation adapter should get the same
  symmetric exemption, not new coverage machinery.
- **F10** [ ] — what is the *right* size/shape for the digest — one sentence always, or
  one-to-two depending on how much the dimension's evidence actually says? The three
  drafted examples above are the first material to test this against; untested until the
  operator reacts to a live rendering.

## Not Yet Settled

- **F10** — digest length/shape is a style question best settled by iterating against
  real assertions, not decided in the abstract.
- Whether `_target_stats` (F3) numeric material ever feeds this feature, or stays
  Scorer-internal — no current need identified; flag if a later ordering/triage want
  surfaces one.
