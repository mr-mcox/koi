---
feature: review-ux
type: scouting
date: 2026-08-31
commit: efe0c2d
parent: ./scouting.md
---

## What We're Doing

Operator's framing, this session: the biggest pain point right now is the sorting and
presentation of the ranking. Three threads, possibly three separate features, some
deferrable:

1. A suspected bug: after updating ratings, sort order doesn't change.
2. Band labels (`established`/`no path`/etc.) may not be helpful — thresholds are blurry.
   Unclear what `standing` even is to the operator, and whether raw values should show at
   all.
3. Longer-term: sparkline-style mini visualizations to see how an opportunity stacks up
   without false precision. Immediate irritant: the per-opening `standing 0.018 / reach
   0.022 / ceiling 0.791` block reads as noise, not signal.

## Findings

- **F1** [x] — `src/screen/web/routes.py:128-148` (`_queue_items`) and
  `src/screen/api/routes.py:70-78` (`GET /queue`) both call
  `score_opening(assertions, config)` with **no `rulings`/`dimension_rulings` argument** —
  every recorded `AssertionRuling`/`DimensionRuling` is invisible to both the queue's sort
  key and its band. Only the per-opening rating page (`_rating_context`,
  `routes.py:214-260`) applies rulings. Confirms the operator's suspicion as a real,
  reproducible bug, not a misread — closes thread 1 as a defect, not a design question →
  bearing Done When.
- **F2** — this exact gap was already found and named: commit `048a068` ("queue-rulings
  gap") flagged it in `docs/CURRENT.md` on 2026-08-29 and it was never picked up — CURRENT
  drifted onto `dimension-ruling-flat-gradient.md` instead. Not a new discovery; a
  known, parked defect finally being scheduled.
- **F3** — `src/screen/web/templates/_rating_content.html:1-6` — the per-opening score
  block renders raw floats: `standing {{ "%.3f" }}`, `reach {{ "%.3f" }}`, `ceiling {{
  "%.3f" }}`. This is a direct violation of domain-model.md wall 4 ("Precision ranks;
  bands display... a single review must never produce '6.7/10'") and decisions.md S6
  ("never decimals... a single aggregator review must not produce '6.7/10'") — not a
  judgment call, an already-broken invariant. `queue.html:11` does the same for `standing`
  only (`"%.3f"`).
- **F4** — `src/screen/score/band.py` — `band_for` derives five labels
  (`no path`/`contender`/`established`/`capped`/`wide open`) purely from where
  `standing`/`reach` fall relative to four config thresholds
  (`scoring.yaml`: `bar`, `bands.contender/settled/reach_capped/reach_wide`). The docstring
  is explicit about intent: "Named for what it implies... not for how good the opening is."
  So "established" isn't meant to be a quality label; it's meant to mean "reach ≈
  standing — no path left to move it further even with a good pass." The operator's
  "blurry thresholds" complaint may be a **legend/explanation gap**, not a wrong mechanism
  — nothing in the UI currently states what each band *means* (only the CSS class name is
  shown, no tooltip/legend).
- **F5** — `scoring.yaml:38-43` + open-questions.md #9 — the four band thresholds are
  explicitly named unmeasured placeholders ("set off eleven observations, seven
  synthetic... expected to move with real ranking use") and #9 states the exact settling
  condition: "batch ranking over a real queue. If the live section is empty or everything's
  a contender, the dials move." This is a **named volatility area**
  (domain-model.md "Named volatility areas") — retuning the numbers is open space, but
  redesigning the five-label taxonomy itself would be a bigger, separate call.
- **F6** — decisions.md S4/S5 (D20/D21) + domain-model.md wall 7 — `standing` is the only
  legitimate sort key; `reach` never sorts, by design, because it saturates (an empty
  record out-reaches a researched one). Any redesign of what's displayed/sorted must keep
  this pair distinct on the wire — a "combined score" or single number blending them would
  reopen a three-times-rejected mistake path (S1's point-estimate rejection).
- **F7** — decisions.md S6, domain-model.md wall 4/5 — "wide because negotiable" and "wide
  because unexamined" must never share a display label. Any new mini-visualization
  (sparkline) needs to keep this distinguishable — a flat bar spanning `[mean-hw,
  mean+hw]` can't alone show *why* it's wide (unexamined prior vs. deliberately wide
  DimensionRuling pin vs. genuine assertion disagreement).
- **F8** — `docs/features/review-ux/dimension-ruling-flat-gradient.md` (status: proposed,
  never implemented) — an almost-identical idea already has a bearing: a flat-band CSS
  gradient rendering `_TargetStats`' `(mean, half_width)` per dimension row, explicitly
  ruling out curved/Gaussian rendering ("would imply precision the model does not have").
  This bearing is **stale but directly reusable terrain** for the sparkline idea — same
  seam (`_stats_for_target`, `scorer.py:104`), same "flat, not curved" constraint, same
  low-opacity/context-not-verdict framing. The sparkline ask may be this bearing generalized
  from one dimension row to a compact per-opening summary (queue-level), not a new
  mechanism.
- **F9** — `src/screen/score/scorer.py:41-101` (`_TargetStats`, `_stats_for_target`,
  `_dimension_ruling_stats`) — the exact numeric substrate for any mini-viz already exists
  and is exposed per target: `(n, mean, half_width)`, already used by the (unbuilt)
  flat-gradient bearing. No new scoring code needed to compute what a sparkline would show;
  this is a display-layer-only feature at the data level, same as F8.
- **F10** — decisions.md S1 worked example (mediocre-fully-researched 0.50/4% vs.
  strong-but-hybrid 0.47/31%) — the entire point of standing-as-probability is that two
  openings with *similar-looking* raw numbers can have very different P(> bar). A queue
  redesign that leans on raw `standing`/`ceiling` numbers risks re-introducing exactly the
  "sorts backwards" failure S1 was built to avoid — display must keep showing the
  probability framing (or a faithful compression of it), not collapse to a mean-like
  number.
- **F11** — no code or doc currently defines "what is `standing`" for an operator-facing
  glossary/tooltip — `domain-model.md`'s Scorer section is the only plain-English
  definition ("P(> bar) now") and it's not surfaced anywhere in the UI. The operator's "I'm
  not sure what standing is" is confirmed as a real gap, not a rhetorical complaint.
- **F12** — `src/screen/web/templates/queue.html:1-17` — the queue is a flat `<ol>`,
  company/title, band chip, raw standing float, two links. No visual hierarchy beyond band
  color-coding (`app.css:44-79`, one CSS class per band, five hardcoded colors). Any
  redesign of band display touches this file plus `app.css`'s five `.band-*` rules plus
  `_rating_content.html`'s duplicate band chip.
- **F13** [ ] — is "raw values displayed at all" (standing/reach/ceiling as floats) an
  operator-facing debug convenience being relied on, or pure accidental noise the operator
  wants gone entirely? F3 says it's a wall violation either way, but removing it outright
  vs. replacing with a coarser display are different-sized changes.
- **F14** [ ] — for the sparkline idea: is the audience the **queue** (compare N openings
  at a glance, one bar per row) or the **per-opening rating view** (one bar per dimension,
  i.e. F8's flat-gradient bearing scaled up) — or both? These are different-sized builds:
  queue-level needs a new compact glyph; per-opening already has a stale bearing.
- **F15** [ ] — should the sort-bug fix (F1) be scoped *only* to closing the gap
  (queue calls `score_opening` with rulings, matching the rating page), or does the
  operator want this bundled with the band/display rework? Bundling risks conflating a
  clear regression fix with a design decision that needs its own scrutiny.

## Not Yet Settled

- Whether band taxonomy itself (five labels) gets redesigned, or only its thresholds get
  retuned (F4/F5) — operator said labels "may not be helpful," which reads as open to
  either.
- Whether raw standing/reach/ceiling display is removed, replaced with a coarser
  band-only display, or kept behind a debug affordance (F13).
- Sparkline scope: queue-level, per-opening, or both (F14); this may be the piece most
  worth deferring given F8 already has unbuilt, unreviewed terrain of its own.
