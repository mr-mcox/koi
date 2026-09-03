---
feature: review-ux
type: scouting
date: 2026-08-31
commit: 396d6a76b87632a5f7d396a650e02b96fb2ae241
parent: ./dimension-ruling.md
---

## What We're Doing

Operator's framing: a `DimensionRuling` pin is computed against the assertions that
existed at the moment it was made. When new assertions land under that target later, the
pin goes stale but nothing marks it as such or routes it back to the operator. Rather than
inventing a new reopening-nomination mechanism, the operator recalled (correctly) that
target stats are already "dimension ruling if present, else aggregate the assertions" —
and proposed stamping the assertions known at ruling time on the `DimensionRuling` itself,
so scoring can interpolate back toward the raw assertion aggregate as new evidence
accumulates, and "is this target available/due for re-ruling" falls out of the same
stamped state as a computed value, rather than needing a new stored flag or nomination
entity.

## Findings

- **F1** — `src/screen/score/scorer.py:104-116` (`stats_for_target`) — confirms the
  operator's recollection exactly: `if target in dimension_rulings: return
  _dimension_ruling_stats(...)`, else `_target_stats(assertions, ...)`. Binary override,
  no blending, no notion of "since when."
- **F2** — `src/screen/score/scorer.py:94-101` (`_dimension_ruling_stats`) — the pin's
  `TargetStats` is `n=inf, mean=ruling.mean, half_width=f(settledness)`. `n=inf` is why
  nothing underneath can move it: it isn't merely weighted heavily, it is definitionally
  un-outweighable by any finite amount of new evidence.
- **F3** — `src/screen/score/scorer.py:56-72` (`_target_stats`) — the *ordinary* (unpinned)
  path already does exactly the weighted-shrinkage math a "drift back toward assertions"
  design would want: `mean = n*sample_mean/(n+1)`, `half_width = 1/sqrt(n+1)`, `n = sum of
  provenance_weight` across the target's assertions. Provenance-weighted blending is not
  new machinery to build — it's the formula already running for every unpinned target.
- **F4** — `docs/architecture/decisions.md` S8 — "provenance sets variance... never
  multiplies fit" is the load-bearing rule the blending formula in F3 already obeys. Any
  drift mechanism that reuses F3's formula inherits this for free; one that invents a
  separate decay curve does not automatically inherit it and would need its own
  justification against S8.
- **F5** — `docs/features/review-ux/dimension-ruling.md` §Done When / §Agreed — shipped,
  `status: done`, tested contract: a pin supersedes "any per-assertion rulings underneath"
  and is "independent of the assertions filed against it." `tests/test_scorer.py`
  (`test_dimension_ruling_override_ignores_assertion_level_rulings_for_same_target`,
  `test_dimension_ruling_override_changes_target_stats_independent_of_assertions`) assert
  this for the assertions that exist *at the time of the pin*. Nothing in that Done When or
  those tests constrains behavior toward assertions filed *after* the pin — the shipped
  contract is silent on drift, not opposed to it. A mechanism that only lets *new*
  (post-pin) assertions pull the blend, while leaving pre-existing ones fully superseded,
  satisfies every existing test unmodified (§Recalibrate When on this scouting's future
  bearing should still name this explicitly, since it's the boundary the whole design
  leans on).
- **F6** — `docs/features/review-ux/dimension-ruling.md` §Agreed — "Pins are not
  revertable — no unset control; resubmission still replaces the value" — decided,
  operator-agreed. A drift mechanism must not read as a delete/unset path: the pin's stated
  `mean`/`settledness` should stay retrievable and displayed even as its *scoring weight*
  erodes; only the *contribution to standing* drifts, not the record.
- **F7** — `src/screen/types.py:171-199` (`DimensionRuling`) — carries `id`, `opening_id`,
  `target`, `mean`, `settledness`, `created_at`. No assertion-snapshot field of any kind
  exists yet; this is new surface, not a rename.
- **F8** — `src/screen/types.py:203-217` (`DimensionDigest`) — the *exact* pattern already
  exists one door over: `assertion_count` stamped at compute time, "the staleness key:
  assertions are append-only (Wall 6), so a monotonic count comparison against the
  target's current assertion count is exact and sufficient to detect a stale digest." A
  `DimensionRuling.assertion_count` (or weight-sum) stamped the same way is not a new
  pattern for this codebase — it is this one, reused one door over.
- **F9** — `docs/features/review-ux/scouting.md` (parent, "What We're Doing") — operator
  principle stated for research state generally: "computed from the saved transcript, not
  stored as separate state — this also lets the system identify [staleness]." A computed
  `is_stale`/`assertion_count` diff is the same principle applied to dimension rulings,
  not a new one.
- **F10** — `docs/architecture/decisions.md` E5 / `docs/architecture/open-questions.md` #3
  — the adjacent mechanism (research-pass reopening) is explicitly **routed, not
  auto-acted**, "the anti-churn rule until a better one is earned," settled empirically by
  a nomination log later. A parallel "reopening nomination" entity for dimension rulings
  would duplicate this pattern rather than reuse it, and would add a second unmeasured
  anti-churn threshold next to one (OQ3) that's already unmeasured.
- **F11** — `src/screen/score/triage.py:85-137` (`rating_task_candidates`) — already *is*
  the routed-surface mechanism for "what's worth the operator's attention next": a pinned
  target is excluded from candidates unconditionally (`if a.target in dimension_rulings:
  continue`; `if target in dimension_rulings: ... continue`). If staleness is computed
  (F8-style), the natural place to surface it is here — a stale pinned target re-enters the
  candidate list — not a new Inbox-style entity. This reuses F10's spirit (routed, not
  auto-acted: reappearing in the triage list is exactly "routed for the operator to look
  at," never a silent score change) without inventing a second mechanism next to it.
- **F12** — `docs/architecture/domain-model.md` §Workflow — "Inbox" (rulings,
  undetermined-fit adjudications, reopening nominations, rubric feedback) is a named
  concept but **`grep -rn "Inbox\|inbox" src/screen --include=*.py` returns nothing** —
  it does not exist in code yet. Anything routed there today has no home; F11's reuse of
  the already-built triage candidate list sidesteps needing to build one for this.
- **F13** ⚠ — `docs/architecture/decisions.md` S8, `docs/architecture/open-questions.md`
  #1 — provenance-rung widths (`provenance_weight` in `scoring.yaml`) are *still*
  unmeasured placeholders after months of use, and `dimension_ruling_hw_max/hw_min` are a
  second, also-unmeasured placeholder pair. A drift mechanism needs a **third** dial — how
  much weight a pin itself carries relative to an assertion, so new assertions can
  eventually outweigh it — landing on exactly the failure mode AGENTS.md names ("a cost
  model fitted to no data is a guess with decimal places") unless it's built as a *named
  config value the operator owns* from day one, same as the other two.
- **F14** [!] — reframing the pin as a weighted pseudo-assertion inside `_target_stats`'s
  existing sum (rather than the current hard `n=inf` override) is the more elegant version
  of F3/F8 combined: `n = pin_weight + sum(new-assertion weights)`,
  `mean = (pin_weight*pin.mean + Σ new)/  (n)`, reusing the shrinkage formula verbatim. But
  "new" must mean *assertions with `created_at`/id not covered by the stamped snapshot*,
  never *all* assertions — conflating the two would silently reopen F5's shipped
  independent-of-pre-existing-assertions guarantee. This distinction is the crux of the
  design and should be named explicitly in any bearing, not left implicit in the formula.
- **F15** — `src/screen/score/types.py:39-53` (`ScoringConfig`) — a new dial
  (`dimension_ruling_weight` or similar) lands here and in `scoring.yaml`, following the
  existing `dimension_ruling_hw_max/hw_min` precedent already in both files
  (`src/screen/score/loader.py` reads `scoring.yaml`; not yet inspected line-by-line but
  the existing `dimension_ruling` block is the template to extend, not replace).
- **F16** — `tests/test_scorer.py`, `tests/test_triage.py` — established test shape for
  this exact area: construct assertions with explicit provenance/fit, construct a
  `DimensionRuling`, assert on `standing`/`half_width` deltas. A drift feature's tests
  follow this shape directly (assert standing moves as new post-pin assertions accumulate;
  assert it doesn't move at all with zero new assertions, preserving F5's contract).

## Open

- **F17** [x] — operator: stamp assertion ids (the exact-partitioning option) — "everything
  else can be computed." `DimensionRuling` gains a `covered_assertion_ids: list[str]`
  (or equivalent) snapshot at ruling time; "new" at score time is precisely
  `{a.id for a in assertions if a.target == target} - covered_assertion_ids` → §Done When
- **F18** [x] — operator: asymptotic, not floored — a pin ruled on one assertion and then
  diluted by nine new ones should end up heavily diluted; the existing shrinkage formula
  (F3) already produces exactly this (`half_width = 1/sqrt(n+1)`, `n` growing) with no
  floor needed, provided the pin itself enters as a large-but-finite weight rather than
  the current `n=inf` → §Approach, §Recalibrate When (if a floor turns out to be wanted
  after all, the weight dial (F13) is where it would live)
- **F19** [x] — operator: reopening is binary (any new assertion under the target
  re-surfaces it in triage), but the triage list's *ranking* is quantified — a pin diluted
  by a 10th assertion when 9 already existed ranks lower than a pin diluted by a 2nd when
  only 1 existed, because swing is proportional to how much the new weight can move the
  blended mean/half_width, which is exactly `rating_task_candidates`' existing best-vs-worst
  swing computation (`triage.py:39-82`) run on the post-drift blended stats — no new ranking
  formula, the existing one already produces this ordering once drift is real → §Approach
- **F20** [x] — operator: add an intermediate border state — a stale pin (covered ids ⊊
  current target assertions) gets a visually distinct border from both an unpinned pad
  (`app.css:300`, `border: 1px solid var(--rule)`) and a fresh/fully-current pin
  (`app.css:311-313`, `.dimension-ruling-pin { border: 2px solid var(--ink) }`) —
  `--ink-muted` (`app.css:17`) is the already-defined intermediate tone, unused elsewhere
  for a border, and the natural candidate for a `.dimension-ruling-pin-stale` rule → §Done
  When. Also, operator: main has diverged (styling commit `84c08e5`) since this worktree
  branched — rebased `resumable-research` onto `main` this session (local branches only, no
  remote); one merge-fallout regression fixed in transit
  (`tests/test_score_loader.py:19`, `top_k` assertion left at the pre-rebase value `10`
  after `scoring.yaml`'s comment-documented drop to `5`) — unrelated to this feature, noted
  here only because it surfaced during this session's rebase.
- **F21** [x] — operator: backfill `covered_assertion_ids` for existing dimension rulings
  via migration SQL, populating from the assertions that existed at the ruling time → §Done
  When

