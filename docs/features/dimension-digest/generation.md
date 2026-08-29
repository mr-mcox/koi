---
feature: dimension-digest
type: bearing
date: 2026-08-29
commit: 4ed61f7
branch: main
status: orienting
scouting: ./scouting.md
parent: ./bearing.md
---

## Problem

Produce and cache a one-to-two-sentence, LLM-generated prose gist of a dimension's
assertion mix — never a verdict, count, or Fit word — invalidated only when new
assertions land, not recomputed per page view. Terrain: [scouting.md](./scouting.md).

## Done When

- [ ] A digest can be generated for (opening_id, target) from its current assertions
      → new unit test against a `FakeDigester`, no live model call
- [ ] The digest text never contains a Fit word (Poor/Mixed/Strong) or a bare number
      → test asserts this on generated output
- [ ] The digest never restates that it is a summary ("N assertions show...") — style
      test against a banned-phrase list seeded from the operator's own examples
      (→ scouting "What We're Doing")
- [ ] Calling generation twice with an unchanged assertion set returns the cached value,
      not a fresh model call → test with a fake digester asserting call count
- [ ] Adding a new assertion to a target invalidates its cached digest → test: cache after
      1 assertion, add a 2nd, assert regeneration happens
- [ ] `uv run python scripts/check.py` passes, including the new migration

## Approach

- New BAML function, `DigestDimension` or similar, alongside `ExtractAssertions` — takes
  the target's assertions (chunks + fit + citations) and rubric text for that dimension,
  returns prose. Behind a Protocol (`DigesterProtocol`) + live adapter + `FakeDigester`,
  mirroring `ExtractorProtocol`/`BAMLExtractor`/`FakeExtractor`
  (`src/screen/extract/protocol.py`, `baml_extractor.py`) (→ scouting F8).
- Live adapter gets the same coverage exemption as `baml_extractor.py`
  (`scripts/check.py` `OMIT_FROM_COVERAGE`) (→ scouting F9).
- New table `dimension_digests(opening_id, target, digest, assertion_count, computed_at)`,
  keyed `(opening_id, target)`, one additive migration file. No change to
  `assertions`/`openings`/`companies` (→ scouting F7).
- Cache invalidation key is the assertion count for that `(opening_id, target)` — append-
  only assertions (wall 6) make monotonic count comparison exact; no hashing or diffing
  (→ scouting F5, F6). Regeneration happens on next read after the count changes, not
  eagerly on write.
- Prompt/style: draft against the operator's worked Coinbase examples (→ scouting "What
  We're Doing"), iterate before finalizing (→ scouting F10).

## Not Doing

- No display/grouping changes — that's `display.md`.
- Not scoring or feeding the digest back into the Scorer.
- Not touching `_target_stats`'s numeric material (→ scouting F3) — no identified need yet.

## Testing

Test-first by default. Exempt:
- The live BAML digest adapter (mirrors `src/screen/extract/baml_extractor.py`'s existing
  exemption) — calls an external LLM service, no unit coverage by design.

## Recalibrate When

- The banned-phrase/style test can't reliably catch bad output — the operator's read of
  live-generated digests is the real signal; if several read badly despite passing tests,
  stop and revisit the prompt with them directly rather than iterating on the test alone.
- A dimension has zero assertions — digest must degrade to explicit "not yet examined"
  text, not an empty or hallucinated summary.
- Assertion count proves an unreliable staleness signal in practice (e.g. a future
  editing/retraction path breaks append-only) — revisit the invalidation key then.

## Agreed

- Cached and invalidated by assertion count, not recomputed on every page view — an LLM
  call per view was flagged as pricey (→ scouting F5, operator).
- Style: reject self-referential summary phrasing (→ scouting, operator's worked
  examples); exact length/tone stays open, settled by iterating with the operator.
