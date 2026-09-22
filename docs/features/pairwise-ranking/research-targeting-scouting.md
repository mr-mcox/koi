---
feature: pairwise-ranking
type: scouting
date: 2026-09-20
commit: 2dc4f80
parent: ./bearing.md
---

## What We're Doing

Parent bearing §Done When: "Research turns concentrate on openings near the top-K boundary"
(→ bearing.md, citing this node). Scouting F39/F40/F73 already framed it: the draw weight
that picks which opening gets the next research turn ignores rank entirely, so a turn can
land on an opening that structurally cannot reach top K, or be withheld from one sitting
right at the boundary where an answer would actually change the top 5.

## Findings

- **F1** — `src/screen/score/bandit.py:16-25` (`aggregate_uncertainty`) — pure
  `(assertions, config, rulings) -> float`: dimension-weighted sum of `TargetStats.half_width`
  across every scored dimension. No pool, no rank, no top_k — an opening's own examined-ness
  is the entire signal.
- **F2** — `src/screen/research/batch.py:271-292` (`opening_weight`, `eligible_weights`) —
  the only caller of `aggregate_uncertainty`. `eligible_weights` maps every screening opening
  with budget headroom to this per-opening scalar; `draw_opening` (bandit.py:29-40) samples
  from it proportionally. Recomputed fresh before every draw (batch.py:414, 524).
- **F3** — `src/screen/research/batch.py:39` — `research/batch.py` already imports
  `screen.score.bandit` and `screen.score.types.ScoringConfig`; a call into `screen.api.pool`
  (`rank_screening_pool`) would be a new import, not a new dependency direction — no girder
  named `research/ never imports score/` is crossed. `research/` importing `api/` would be new:
  today nothing under `research/` or `score/` imports `api/` (checked by grep); only
  `web/routes.py` and `api/pool.py` import `api.scoring`/`api.pool`. Architecture names
  `intake/` never imports `research/` as the one directional girder (architecture/README.md);
  it says nothing about `research/` importing `api/`.
- **F4** — `src/screen/api/pool.py:73-101` (`rank_screening_pool`) — the one function that
  assembles a `PoolScoreResult` from the DB: takes a `sqlite3.Connection` and `ScoringConfig`,
  returns `PoolScoreResult` with `opening_ranks` (`OpeningRank.p_top_k`, `.expected_rank`,
  `.rank_q10/50/90`, per `src/screen/score/types.py`). This is the one existing entry point
  that could supply boundary information to a reweight, called once per batch draw the same
  way `eligible_weights` already is (F2).
- **F5** — `src/screen/score/scorer.py:191-200` — `rank_pool` already computes
  `current_top_k_indices` and `settledness` (overlap between sampled top-K and current top-K)
  internally but does not return the per-opening "how much does this opening's own resolution
  move the boundary" quantity directly — only `p_top_k` and rank quantiles are on
  `OpeningRank`. A boundary-focused reweight has `p_top_k` to build from, not a ready-made
  per-opening VOI number.
- **F6** — scouting F29 (parent) — the comparison picker (`compare_picker.py`) already
  implements a LUCB-style boundary rule for *pairwise comparisons*: pick the top-K opening
  with lowest plausible value vs. the outside opening with highest plausible value. The same
  shape (`p_top_k(1 - p_top_k)` from scouting F40) is proposed for research, not yet built.
- **F7** — scouting F40 (parent), F73 (parent) — operator agreed to do the research
  reweighting in this feature (F73), proposed shape: boundary-weighted
  `P(top_k) · (1 - P(top_k))` replacing/augmenting the aggregate half-width signal (F40).
  Not further specified — open thread on how it combines with F1's uncertainty term.
- **F8** — `src/screen/research/bandit.py` doesn't exist; `aggregate_uncertainty` lives in
  `score/bandit.py` since it's a pure function mirroring `scorer.py` (bandit.py:1-5 docstring).
  A boundary-aware version needs the pool (F4), which needs the DB — the impure assembly
  belongs in `research/batch.py` or `api/pool.py`, not in the pure `score/bandit.py`, matching
  the split `opening_weight`/`aggregate_uncertainty` already have (F1/F2).
- **F9** — `tests/test_bandit.py` — all four existing tests exercise `aggregate_uncertainty`
  and `draw_opening` as pure functions against synthetic assertions/weights, no DB, no pool.
  A boundary-aware reweight that needs `PoolScoreResult` breaks this pattern unless the pool
  trace is passed in as a plain argument (already the shape `rank_pool` itself takes — no I/O).
- **F10** — `src/screen/research/baml_planner.py:70-96` (`rank_targets`,
  `_target_uncertainty`) — a *separate* uncertainty signal, per-target within one already-
  chosen opening (`1/sqrt(n+1)` from provenance-weighted count), independent of
  `aggregate_uncertainty`. Parent scouting F38 notes it already has an assertion-count
  fallback since `DimensionRuling.settledness` retired (S11) — this planner-internal ranking
  is unaffected by a boundary reweight, which operates one level up (which opening, not which
  target within it).
- **F11** — `scoring.yaml:38-42` — `top_k: 5`, "unmeasured placeholder" — same status as
  every other dial in this file (comment says so explicitly); a new dial for how boundary
  weight combines with uncertainty weight would carry the same status.
- **F12** — decisions S9 — rank is pool-scoped and computed jointly; `p_top_k` for one
  opening is not stable in isolation — it depends on every other screening opening's current
  assertions. Recomputing `rank_screening_pool` before every batch draw (matching F2's existing
  "recomputed fresh… so a just-spent turn's new assertions immediately affect the next draw")
  is the only way a boundary signal stays current turn-to-turn.
- **F13** — `scoring.yaml:14` — `samples: 200000`. `rank_pool` is a Monte Carlo call over the
  whole screening pool; calling it once per draw (as eligible_weights already recomputes every
  draw, F2) adds one full pool score per draw where today's `aggregate_uncertainty` path was
  pure-Python per-opening. Cost is untested here — `rank_pool` is measured "plausible" only
  on `/` render in rank-pool.md's Recalibrate When ("~2s"), not in a tight per-draw batch loop.
- **F14** [!] — F13's cost is the batch loop's, not the web request's — rank-pool.md's "if
  rendering `/` on the live pool takes over ~2s, stop" doesn't cover it. → Recalibrate When
  a batch run's per-draw latency becomes visibly slower with the pool call added.
- **F15** — `src/screen/research/batch.py:283-297` (`eligible_weights`) docstring: "Recomputed
  fresh on every call". A boundary-weighted version would need the same freshness, so the
  natural seam is inside `eligible_weights`/`opening_weight`, not a one-time weight computed
  at batch start.
- **F16** [x] — how does boundary weight (`p_top_k(1-p_top_k)`) combine with the existing
  uncertainty weight (`aggregate_uncertainty`)? **Resolved:** product (`uncertainty × boundary`),
  not gate — operator wants breadth-first coverage that raises fresh/under-examined openings
  over fine-grained ranking among already-examined boundary cases → `research-targeting.md`
  §Agreed.
- **F17** — parent scouting F1 — "north star is which 5 are my front runners… a pipeline of
  companies to apply to fresh." Worked check (5-opening synthetic pool, top_k=3, one
  Strong-everywhere opening, three ratified-Mixed openings straddling the boundary, one
  wholly unexamined): `p_top_k` = 1.00 (clear winner), 0.50/0.50/0.50 (the three boundary
  ties), **0.497 (fresh, zero assertions)** — `boundary_weight = p_top_k(1-p_top_k)` gives
  0.000, 0.250×3, and **0.250 for fresh**, indistinguishable from the boundary-contested
  openings. A pure boundary weight does not starve a fresh opening — its wide Gaussian prior
  already straddles the cutoff the same way a contested examined opening does.
- **F18** — confirmed by F17's run (`rank_pool` called directly, `screen.score.scorer`,
  numpy seed 1, 20000 samples) — no committed test covers this shape yet; the demonstration
  lives in this finding, not yet in `tests/test_scorer.py`.
- **F19** — worked scenarios (3-dim synthetic pool, `top_k=3`, 30000 samples) showing where
  the combination rule has material effect (numbers from `screen.score.scorer.rank_pool` and
  `screen.score.bandit.aggregate_uncertainty`):
  - **Scenario A** (clear top, two boundary openings, fresh, clear bottom): `clear_top` gets
    `unc=0.74, p_top=1.00, bound=0.00, product=0.00`; `boundary_A` and `boundary_B` are
    `bound=0.003/0.149, unc=0.94, product=0.003/0.139`; `fresh` is `unc=6.00, p_top=0.185,
    bound=0.151, product=0.905`; `clear_bottom` gets `product=0.000`. Product all but
    eliminates the near-certain top and bottom, but fresh (not currently in top K) outranks
    the actual boundary-contested openings.
  - **Scenario B** (strong top, fresh, partial-only-domain, mediocre boundary): `fresh`
    `product=1.473` > `partial` `0.898` > `mediocre_boundary` `0.211`. The partial opening
    (only the lowest-weight dimension examined) outranks the more fully examined boundary
    opening, purely because it still has high residual uncertainty.
  - **Scenario C** (8 similar mediocre openings, one star, one fresh, `top_k=5`): all 8
    boundary-contested mediocre openings get `product≈0.19`, while `fresh` gets
    `product=1.47`. A pure boundary-only weight would give fresh `0.246` and the mediocre
    openings `0.156-0.159` — much closer.
  - **Scenario D** (`top_k=2`, one "one-hit wonder" with a single Strong `stretch`
    assertion, two mediocre fully examined, one fresh): one-hit `unc=4.00, p_top=0.965,
    product=0.134`; mediocre `unc=1.20, p_top≈0.29, product≈0.245`; fresh `unc=6.00,
    p_top=0.456, product=1.489`. Product prioritizes fresh and the mediocre boundary over
    the current #1 that is built on almost no evidence.
- **F20** — the two natural combination rules from F19's numbers:
  - **Product** (`uncertainty × boundary`) strongly favors unexamined or partially-examined
    openings at the boundary; it downweights openings that are already near-certain to be
    inside or outside top K even when they still have residual uncertainty. It risks turning
    the research pass into a "first-pass coverage" pass rather than a "settle the current
    top K" pass.
  - **Gate** (`boundary ≥ threshold`, then sample by `uncertainty`) first prunes the clear
    inside/outside cases and then uses uncertainty to pick among the boundary set. It keeps
    research focused on current decision-relevant openings but needs a threshold; a too-high
    threshold can exclude fresh openings whose prior has not yet concentrated enough to earn
    a high boundary weight, a too-low threshold approaches pure uncertainty.
- **F21** — operator (2026-09-20) — product, not gate: breadth-first, raise opportunities
  that might otherwise get lost; the queue itself already lets the operator visually discount
  a high-ranked opening whose band is still wide because it needs more research. This aligns
  the research draw with the "pipeline of fresh companies" half of the north star (parent
  scouting F1) rather than the "settle the current top K" half.
