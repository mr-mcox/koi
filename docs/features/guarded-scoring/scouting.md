---
feature: guarded-scoring
type: scouting
date: 2026-10-22
commit: e7f39d8
---

## What We're Doing

Operator's framing: openings the operator keeps rejecting on one dimension — TRM Labs on
mission ("enabling law enforcement… I wouldn't want to work there"), Rula on craft direction
— still landed in the top 5. The fix is nonlinear: "a 'move to San Francisco' should tank a
role (I'm not moving), but on the upper end, 'company A is a bit more remote friendly than
company B' is more of a preference than a hard stop." Same shape for mission, schematic
("if it's not really a staff role, I should probably pass"), and internal culture ("some
possible signals/reputation that could tank, but doubt that it's going to contribute that
much to upside"). Craft direction "not to the same extent." Flatten weights to 1/2/3.

Properties the operator asked for:
1. Top contenders scrutinized and stable, without false precision — "knowing that
   opportunity is 3 vs 7 is more important than 13 vs 17."
2. No slow starvation at the bottom — "cool with bottom 2/3 being roughly a lottery with
   lots of churn as long as they have a chance to surface." TRM's ideal path: low and
   uncertain → examined, craft/location solid → rises → mission examined → tanks → move on.
3. Keep it as simple as possible.

## Findings

Measurements below were run during the session on a read-only copy of `data/live/screen.db`
at this commit, using the real scorer (`pool_for_screening`) plus post-hoc transforms of
`PoolScoreResult.dimension_trace`. The scripts were scratch (`/tmp/koi-analysis/`) and
are not reproducible from the repo; the operator reviewed the outputs in-session.

- **F1** — operator — TRM Labs, Rula (Provider), Affirm rank #4/#5/#6 against gut; TRM is
  disliked on mission, Rula on craft direction, Affirm "to a lesser extent".
- **F2** — measurement — the three's lead over ranks 7–15 comes from `location` (weight 6)
  and `internal_culture` (weight 4), 40% of total weight 25. TRM vs that tier, in overall
  points: mission −.032, comp −.028, location +.053, culture +.059. Mission's entire −1..+1
  range is worth 0.08 overall; TRM with mission pinned at −1 still ranks #6.
- **F3** — measurement — TRM's mission posterior is −0.28: 9/9 operator losses, plus 4
  provisional Jev wins (vs Forward Financing, Webflow Senior Staff, Root, Smartsheet).
  Without those four, −0.71. Win/loss comparisons carry no margin, so a dealbreaker loss
  counts the same as a mild preference.
- **F4** — measurement — weights 1/2/3 (F7's assignment) plus a guard curve (downside ×3,
  upside ×0.3) on location, mission, schematic, internal_culture: top 7 = Twin Health,
  Phantom, Aleph, Juniper Square, Fireworks, Honor, BetterHelp; TRM #35, Rula Provider #23,
  Affirm #22 — with Jev's TRM wins still in. Adding a craft curve (×2/×0.75) or mission
  weight 3 changed nothing material. A 150-draw sweep of per-dimension curves
  (downside 1.5–6, upside .15–.8) kept the same seven in the top 10 in 100% of draws.
- **F5** — operator — guards: location, mission, schematic, internal_culture. Craft is
  milder ("cool with a more SWE role if everything else is looking really good").
- **F6** — operator — flatten weights to a 1/2/3 scale, not up to 6.
- **F7** [ ] — the 1/2/3 assignment is the agent's proposal, not yet confirmed: craft 3,
  location 3; schematic, mission, internal_culture, trajectory, agentic, compensation 2;
  domain 1. The operator said "change the weights" without adjusting it.
- **F8** ⚠ [x] — decisions S1 property 4 ("a sort favoring a wide-open unknown over
  well-established mediocrity") and S3 — a guard applied per sample makes the queue
  risk-averse. For a Gaussian at 0 with sd σ, E[guarded] = σ·φ(0)·(up − down) =
  −1.08σ; an unexamined dimension (σ = 1/√3) scores ≈ −0.62, between Mixed and Poor.
  Operator resolution: "look where it might be good, apply where it's known good" — the
  queue gives up S1's property; attention (research + compare picker) keeps it by reading
  a guards-off view → §Agreed, §Approach.
- **F9** — measurement — the alternative (bend the estimate, keep the spread) is
  pathological: the ×3 downside slope widens the spread of any slightly-negative opening,
  and P(top-K) rewards width — an unparsed "Unknown – job posting not found" opening rose
  to #4. Rules out estimate-only guards.
- **F10** — `src/screen/score/scorer.py:181-186` — the rollup is
  `weighted += weight * draw` per dimension over the joint draw, then
  `(weighted/total_weight + 1)/2`. One place to apply a per-sample guard.
  `scorer.py:149-155` `_deterministic_quality` is a tiebreak from means.
- **F11** — two attention consumers read the queue's `p_top_k`:
  `src/screen/research/batch.py:288-312` (`eligible_weights` = uncertainty ×
  `boundary_weight(p_top_k)` from `rank_screening_pool`) and
  `src/screen/api/pool.py:366-374` → `src/screen/score/compare_picker.py:291-297` (pair
  priority = max `boundary_weight`, skipped if ≤ 0).
- **F12** — `src/screen/score/bandit.py:31-37` — `boundary_weight(p) = sqrt(p)`, exactly 0
  at p = 0: a pair or opening with P(top-K) = 0 gets no attention. Mechanism of starvation.
  `batch.py:290-291` docstring still says `p_top_k * (1 - p_top_k)` — stale.
- **F13** — `src/screen/score/compare_picker.py:197-212` — `_overall_diff` uses linear
  weights for the P(A>B) skip gate; already a guards-off view.
- **F14** — operator — starvation has happened before in this project.
- **F15** — operator — `top_k` 5 → 10. Cluster of ~7 is stable; 2nd vs 4th doesn't matter.
- **F16** — `scoring.yaml` `top_k: 5`; `src/screen/web/routes.py:160-170` draws the queue
  glyph's boundary at `top_k`, and `scorer.py` settledness is computed over the top K —
  `top_k` also moves the display boundary.
- **F17** [x] — operator — Jev-ruled pairs stay excluded from the picker
  (`compare_picker.py` `_best_dimension_for_pair` docstring); working as designed, other
  pairs kept pushing TRM down, re-admission adds complexity → §Not Doing. Override is via
  `/compare/review` or the direct `/compare?opening_a_id=…&opening_b_id=…&target=…` form.
- **F18** — `src/screen/extract/prompt.py:50` — the rendered rubric heading includes
  `weight:`; changing weights changes text Jev and research read (decisions R4).
  A new yaml key is not rendered unless `_render_one_dimension` adds it.
- **F19** — `src/screen/recalibration.py:441-468` — `parse_rubric_fields` parses rendered
  text, not yaml; an unrendered `guard` key does not affect it.
- **F20** — `tests/test_scorer.py:57-58,106-121` — scorer tests load the real
  `rubric.yaml`/`scoring.yaml`; the kill test asserts a ratified Poor location sinks
  `p_top_k < 0.1` at `top_k=1` against a clean twin. It will exercise the new weights.
- **F21** — decisions S2, S12 — pass/fail gates rejected (three rewrites); heavy additive
  weights rejected by measurement; S12's case for a linear weight measured only the sink
  side. A guard is neither a gate nor a heavier weight.
- **F22** — decisions R10 — `extractive_business` (weight 4) folded into `mission`
  (weight 2); R10 explicitly deferred "if `mission` scores poorly while an opening still
  ranks high in practice". F1 is that case.
- **F23** — domain-model walls 1–2 — provenance never multiplies fit. A guard multiplies
  sampled values by a sign-dependent constant, independent of provenance; not a wall
  crossing, but width now lowers the guarded expectation (F8).
- **F24** — operator — pause after weights + guards + S-decision to review ranking changes
  before the attention changes land.
- **F25** [!] — the attention floor value is unmeasured. Proposal 0.1 on the `sqrt` scale
  (a P≈0 opening gets ~10% of a sure top-K's attention, before the uncertainty factor) →
  §Recalibrate When.
- **F26** — `scorer.py:181-185` — `rank_pool` already keeps every dimension's draw in
  `dimension_trace`; a guards-off view can be computed from the same joint draw without
  resampling.
- **F27** — gates (`scripts/check.py`) all pass at this commit.
- **F28** [ ] — `docs/CURRENT.md` points at `docs/features/opro-recalibration/bearing.md`
  (status orienting). Repoint to this feature, or leave?
