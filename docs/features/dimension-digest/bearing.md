---
feature: dimension-digest
type: bearing
date: 2026-08-29
commit: 4ed61f7
branch: main
status: decomposed
scouting: ./scouting.md
---

## Problem

Rating view is too much raw assertion text to scan per dimension. Wanted: a short,
LLM-generated prose gist of what a dimension's evidence actually says — never a verdict,
never a count-of-assertions restatement — with the assertions still reachable underneath.
Terrain: [scouting.md](./scouting.md).

Carried by children — see `generation.md`/`display.md`/`digest-latency-and-style.md`.

## Approach

Splits into two reviewable leaves, cut along "what generates the text" vs. "how it's
shown," since they have independent reversal costs (a caching/schema decision vs. a
template/routing decision):

- **`generation.md`** — the digest concept itself: what it is, how it's produced
  (BAML function + Protocol/Fake, mirroring `ExtractorProtocol`), how it's cached and
  invalidated (new table, assertion-count-based staleness), and what it must never say.
- **`display.md`** — grouping assertions by dimension in the rating view and rendering
  the cached digest above each group.
- **`digest-latency-and-style.md`** — warm the cache after a research pass, tighten the digest prompt for scanability, and render bullets/line breaks in the view.

## Not Doing

- No dimension-level `Ruling` object (→ scouting F2, operator-origin, out of scope here).
- No change to the Scorer, `Target` vocabulary, or existing tables — additive migration
  only (→ scouting F7).

## Testing

Carried by children.

## Recalibrate When

Carried by children.

## Agreed

- Digest is LLM-generated prose, never a Ruling and never a number — separate from the
  still-open dimension-level Ruling question (→ scouting F2, F4, operator).
- Digest must never restate its own evidence count ("there are three assertions...") —
  it summarizes the *content*, in the voice of someone who read the evidence
  (→ scouting, operator's worked examples).
