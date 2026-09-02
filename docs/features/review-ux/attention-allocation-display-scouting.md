C---
feature: review-ux
type: scouting
date: 2026-09-02
commit: 3edace7
parent: ./attention-allocation.md
---

## What We're Doing

Operator's framing, this session: rather than a new visualization, reuse the existing
lollipop glyph. Add a horizontal marker/tick at the boundary — the standing of whichever
opening currently holds rank K — and show each opening's over/under possibility relative
to that tick as a bar. Wholly right of the tick = safely in the top K, no more research
needed. Wholly left = safely out, no more research needed. Straddling the tick = contested,
where attention should go. The operator is not sold on `ceiling` still earning its place in
the glyph, and floats simplifying or dropping `reach` too.

## Findings

- **F1** — `attention-allocation-computation.md` (status `done`) — the crossing-probability
  computation this display would render already exists and is already wired into the JSON
  `/queue` route (`src/screen/api/routes.py:127-136`); `queue.html` renders none of it yet
  (`docs/CURRENT.md`). This session's proposal is squarely the deferred display leaf, not a
  new mechanism.
- **F2** — `src/screen/score/boundary.py` (`crossing_probability`) — pure function over two
  `ScoreResult`s: fraction of samples where one opening's trace exceeds the K-th opening's
  trace. Already the "which side of the boundary, and how confidently" signal the operator
  is describing as a bar — no new sampling or Scorer primitive needed to drive it (→
  attention-allocation-scouting F33).
- **F3** — `src/screen/score/types.py:80-85` (`ScoreResult.p_stderr`) — Monte Carlo standard
  error on `standing`, already computed. A candidate width if the bar is meant to render an
  *interval* around standing (e.g. `standing ± k·p_stderr`) rather than the single
  `crossing_probability` scalar — these are two different amounts of information with
  different rendering costs (see F8).
- **F4** — `sparkline-visualization.md` Recalibrate When ("the lollipop... starts implying
  false precision or making openings look more similar than they are — stop, the visual
  language needs rework") — this trigger already names the failure mode the operator is
  reporting now. The operator's doubt about `ceiling` is not a new complaint; it's this
  bearing's own escape hatch firing.
- **F5** — `standing-reach-lenses.md` (scouting) F1-F3 — `ceiling` saturates to 1.0 for any
  opening with enough unexamined/wide targets and was already measured (Angi's ceiling at
  1.000) to compress the mid-pack when used as the axis scale-max. Independent prior
  evidence the operator's instinct here is grounded, not a fresh aesthetic call.
- **F6** — `docs/architecture/decisions.md` S5 — `reach` never becomes a sort key, but
  nothing in S5 or wall 7 (domain-model.md) constrains what is *drawn*. Dropping/simplifying
  `reach` in this one glyph does not touch the sort key, which stays `standing` regardless
  (S5, unaffected by any display leaf).
- **F7** — `standing-reach-lenses.md` (scouting) F9 — a separate open question ("what is the
  research-lens sort key") already treats `reach` itself as insufficient signal for "where
  should research go" and proposes swing/leverage measures instead. If the boundary glyph
  drops `reach`, that research-targeting question doesn't get answered by this glyph either
  way — it was never this glyph's job per attention-allocation.md's own scope split
  (computation vs. display, both existing as siblings of a shared signal).
- **F8** [ ] — does the "bar" render `crossing_probability` directly (a single scalar
  0..1, e.g. as a fill-fraction of a fixed-width indicator — reuses F2 exactly as
  computed, no new numeric choice) or render a *confidence interval* around `standing`
  positioned against the boundary tick (`standing ± k·p_stderr`, F3 — needs a chosen `k`,
  a new named-not-measured config value per AGENTS.md "measure before model")? The first is
  cheaper and matches F30/F33's "no false precision" cost bound already agreed for the
  computation leaf; the second gives the operator a literal "how far over/under" reading at
  the cost of an unmeasured multiplier.
- **F9** [ ] — does dropping/simplifying `ceiling`/`reach` apply to the queue row glyph
  only, or also to the per-opening score block? `sparkline-visualization.md`'s Approach
  built both from the same component "start identical" — a queue-only change reopens
  whether the two views still share one component or diverge (that bearing's own
  Recalibrate When: "if divergence is more than CSS it becomes a separate design
  question").
- **F10** — `src/screen/web/routes.py:224-235`, `src/screen/api/routes.py:119-136` — the
  K-th opening's `standing_result` (the boundary reference) is already computed once per
  queue build in both routes; rendering it as a shared tick position per row needs no new
  query, just passing that one value into the per-row glyph alongside what's already there.
