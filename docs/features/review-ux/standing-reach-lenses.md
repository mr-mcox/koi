---
feature: review-ux
type: scouting
date: 2026-09-01
commit: ef18efc
parent: ./attention-allocation-scouting.md
---

## What We're Doing

Operator's framing, this session: the sparkline axis currently scales to the maximum
`ceiling` in the view, which compresses the middle of the pack because a few openings hit
the theoretical ceiling (1.000) almost trivially. The 95%-ceiling scaling idea (scale the axis
to the 95th percentile of ceilings, letting the top 5% clip past the right edge) was
proposed as a quick fix, but the operator wants it kept as its own thread rather than
folded into `band-label-clarity.md`. It may instead belong to the broader replacement for
band labels: **separate sorts/lenses for standing vs. reach**, giving the operator two
views on the same backlog rather than one collapsed ranking.

## Findings

- **F1** — operator, this session — the immediate irritant is not the sparkline glyph
  itself, but that *all* openings look visually similar because the axis is stretched by
  outliers (Angi's ceiling at 1.000, see this session's live data read). The operator wants
  differentiation in the middle of the pack, not more precision at the extremes.
- **F2** — `src/screen/web/routes.py:200` (`scale_max = max((score.ceiling for ...), default=1.0)`) —
  the queue sparkline axis is literally `max(ceiling)` over the current queue. The per-opening
  sparkline uses `score.ceiling` as its own scale. Both are relative, so the bar at 0.60 is
  invisible; the operator cannot read " clears the bar" from the glyph alone.
- **F3** — `src/screen/score/scorer.py:161-171` — `ceiling` is the *theoretical* maximum
  P(overall > bar) when every dimension is at the top of its support and every constraint is
  at its best tolerability. It is designed to be optimistic by construction and saturates at
  1.0 for any opening with enough unexamined or wide targets. Using it as the scale maximum
  is therefore expected to over-zoom and clump the bulk — this is a display-scaling choice,
  not a scoring bug.
- **F4** — decisions.md S5 (domain-model.md Scorer section) — `reach` is explicitly not a
  sort key for the main queue because it saturates: an empty record can out-reach a well-
  researched good one. Any "separate sort by reach" lens must therefore **not** be raw
  `reach`; it must be a VOI-aware signal such as `reach - standing`, a leverage-weighted
  gap, or a research-pass bandit score. Otherwise it reproduces the exact failure S5 rejected.
- **F5** — `rating-voi-triage.md` Approach — the per-opening task-ranking mechanism already
  computes "how much would resolving this move standing" (`_swing`). A queue-level "research
  lens" sorted by a similar opening-level swing (or max per-task swing) would reuse the same
  primitive, not invent a new one — consistent with attention-allocation-scouting F2/F11.
- **F6** — attention-allocation-scouting F4 — the research-pass counterfactual
  (`resolve_favourably`) only detects fully-blank targets. A "research lens" sorted by raw
  reach gap will undercount partially-researched openings (Wheel's case in live data). Any
  lens that claims to show "where research helps most" needs to reason about `half_width`/
  `settledness`, not just presence/absence of assertions, or it will be systematically wrong.
- **F7** — operator, this session — the replacement for the five band labels is not a new
  categorical taxonomy, but **actionable lenses**: standing sorts the "what should I apply
  to" view; a reach/leverage/VOI signal sorts the "what should I research or rate next"
  view. The operator composes the strategy; the system surfaces the signals.

## Not Yet Settled

- **F8** [ ] — is the 95%-ceiling scaling a standalone display tweak, or only meaningful once
  the queue has two lenses? If the queue is going to split into "apply view" (standing) and
  "research view" (leverage), the sparkline axis might need to be per-view or fixed to a
  meaningful absolute scale (e.g., the bar at 0.60), not a relative percentile.
- **F9** [ ] — what is the research-lens sort key? Options: (a) `reach - standing` raw gap,
  (b) max per-target swing from `rating_task_candidates`, (c) a sum or aggregate opening-
  level swing, (d) a separate research-pass bandit score that accounts for F6's half-width
  gap. Each has different noise and saturation properties.
- **F10** [ ] — does the operator want a toggle between two sorted lists, or one queue with
  two sections (apply section above, research section below), or a single list with a
  secondary sort key that still keeps standing primary? The UI shape determines whether S5's
  "reach never sorts" wall needs a formal exception or just a new route name.
- **F11** [ ] — is the per-opening sparkline's own scale (currently `score.ceiling`) also
  wrong? It makes every opening fill its own box, so the operator cannot compare the
  absolute position of one opening's dots against another's. A fixed 0-1 scale or a bar
  reference line might be more honest than either max-ceiling or 95th-percentile scaling.
