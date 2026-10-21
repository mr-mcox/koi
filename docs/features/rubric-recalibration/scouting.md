---
feature: rubric-recalibration
type: scouting
date: 2026-10-20
commit: bbb6a14
---

## What We're Doing

The operator's framing: *"I'd like to have a world where I'm doing a bunch of scoring, then
I run a recalibration pass and get some suggested rubric updates that I can commit/reject
diffs for across all dimensions."* Largely hands-off until it hands over a diff to review.
Explicitly: not a lot of machinery, not prone to errors, not much to maintain, not
reinventing the wheel. Minimum example threshold (operator suggested ~100) so a real test
set exists. Open question from the operator: *is this effectively autoresearch?*

## Findings

### What the corpus can support

- **F1** — `data/live/screen.db` via `comparisons_for_target`, measured 2026-10-20 —
  usable operator comparisons by target (both digests present): `location` 73,
  `compensation` 64, `mission` 44, `schematic` 43, `internal_culture` 34,
  `craft_direction` 29, `trajectory` 9, `agentic` 10, `domain` 9. (Counts shift by 1-2
  between runs as the operator keeps rating.) At the operator's floor of 70 (F13),
  `location` and `compensation` are eligible; at 50, nothing more joins; at 40,
  `mission` and `schematic` join.
- **F2** — same measurement — usable counts are far below raw counts because digests are
  missing for one or both sides (`location`: 129 raw → 71 usable). Any threshold must be
  counted on *usable* pairs, not raw comparisons, or the gate reads as satisfied while the
  evaluator starves.
- **F3** — `scripts/backtest_jev_routing.py` run per-target, 2026-10-20 — forward-run
  bucket counts (right/wrong × sure/unsure at conf ≥ 0.70). Superseded for target choice by
  F17; retained because these buckets are what the loop optimizes:

  | target | n | right+sure | right+unsure | wrong+sure | wrong+unsure |
  |---|---|---|---|---|---|
  | `location` | 73 | 13 | 19 | 7 | 28 |
  | `compensation` (post-fix) | 64 | 0 | 37 | 2 | 25 |
  | `schematic` | 43 | 11 | 11 | 3 | 16 |
- **F4** — `src/screen/extract/prompt.py:12-46`, fixed this session at `bbb6a14` —
  `compensation`'s anchors are defined against `SCREEN_COMPENSATION_BASELINE`, which was
  **never substituted**, so Jev judged every pair against a literal variable name. Now
  resolved at render time and raises `MissingPrivateConfigError` when unset. **All
  `compensation` numbers in F3 predate the fix and are void.** Re-measure before using that
  target for anything.
- **F5** — operator — the feeling that "I'm asked to weigh in unnecessarily" on a dimension
  is *not* reliable evidence of a rubric-wording defect. It pointed at `compensation`, where
  the real cause was F4's missing input. Measure the buckets before accepting a target.

### What the mechanism can and can't be

- **F6** — demonstrated this session — n-gram/keyword mining over digests measures posting
  vocabulary, not operator disagreement: `remote-first` appeared in 15 of 19 cases on both
  sides. The one real `location` finding (silence-on-travel reads as a penalty to the model,
  as neutral to the operator) is a semantic relation between two digests and an outcome, and
  no frequency count surfaces it. **Pattern mining is rejected; an LLM reading labeled cases
  is the pattern-finding mechanism.**
- **F7** — operator, and `docs/features/rubric-realignment/bearing.md` §Not Doing —
  frameworks (DSPy, TextGrad, autoresearch) are search aids at most, never the product
  shape. On *is this autoresearch*: it shares the propose→evaluate→report loop, but a
  generic autoresearch harness optimizes a **prompt**, while the committed artifact here is
  **rubric text**. The useful parts (LLM proposes, measurement filters) are ~100 lines
  against the existing backtest; the harness is the part that would be maintained forever.
- **F8** — `docs/architecture/README.md:26-27`, `src/screen/extract/prompt.py:62-100` —
  rubric text is a **girder**, and one dimension's text feeds extraction
  (`rubric_text_for_baml`), Jev classification (`jev_assertion_classifier.py:59`), and
  verdicting (`backtest_jev_routing.py:104`). A verdict-measured improvement can silently
  degrade the other two stages. The loop measures one stage and must not claim more.
- **F9** — arithmetic, at F1's volumes — with n≈42 and candidate edits differing by 1-2
  cases, beam/evolutionary search over clause edits optimizes sampling noise. At n=42 a
  2-case delta is ~5pp with a 95% CI of roughly ±15pp. **Search is rejected at current
  volume**; propose a small number of candidates, measure, report.
- **F10** — `scripts/backtest_jev_routing.py:99-137,228-260` — already loads operator
  comparisons, fetches digests, calls Jev concurrently, applies `route_verdict`, and reads
  thresholds from `load_scoring_config()`. The recalibration loop is a consumer of this,
  not a reimplementation.
- **F11** — `rubric.yaml:1-6` — "git history is the change log"; `tests/test_rubric.py`
  guards structure and privacy. The accept/reject surface is therefore **the working tree
  plus `git diff`** — a bespoke review UI reinvents a wheel already in use (operator: don't
  reinvent the wheel).
- **F12** ⚠ — F8 plus `tests/test_rubric.py:61-78` — the loop writes to a girder and to a
  file under a privacy gate. A proposed diff must never be auto-applied, and generated text
  must pass `test_rubric.py` before the operator sees it. An LLM that invents a
  compensation figure into an anchor is the specific hazard.

### Method constraints

- **F13** — operator — minimum example threshold (~100 usable pairs) before a target is
  eligible, so a held-out test set is affordable. Exact split and whether 100 is the right
  number are the operator's call.
- **F14** — standard method, and the limit on this session's own `location` work —
  proposing an edit from the same cases used to measure it is circular. With a held-out
  split (F13) the measurement is honest; without one, any reported delta is a smoke test for
  regression, not evidence of improvement.
- **F15** — `docs/architecture/learnings.md:102-119` — the prototype found remediation on 7
  of 7 overrides was `example-only`, zero `rubric-edit`, with an anchoring caveat recorded.
  Some mismatches are *missing operator data*, not bad wording. The loop must be able to
  report "no rubric edit proposed" as a successful outcome, or it will manufacture edits.
- **F16** — operator — output is a **diff**, small, reviewable, with the evidence that
  produced it. The operator stays hands-off until that artifact exists.

### Target selection (measured, 2026-10-20)

- **F17** — `/tmp/order_bias.py`, every pair run forward and swapped, raw probabilities
  compared rather than thresholded labels — **swapping a/b is very nearly a no-op at the
  probability level**, as it must be. `p_clear` symmetry: mean |delta| 0.045 (`mission`),
  0.055 (`location`). `p_a` mirror residual: mean |resid| 0.084 / 0.091.
- **F18** — F17 — **the earlier "self-consistency" metric was invalid and its conclusions
  are withdrawn.** 100% of discrete flips (2/44 `mission`, 11/74 `location`) sit within
  0.15 of the tie boundary. It measured `route_verdict` discretizing a continuous signal at
  an arbitrary cut, not evaluator instability. The claim that `schematic` is too noisy to
  measure (old F18) and that `mission` is the standout (old F19) both rested on it and do
  not survive.
- **F19** — F17 — a **small but real first-position bias** remains: mean *signed* `p_a`
  residual −0.082 (`mission`), −0.036 (`location`), max |resid| 0.31. Nonzero signed
  residual is systematic, not noise. Averaging the two orders removes it and lifts accuracy
  slightly: `mission` 32%→34%, `location` 50%→53%. Cheap, and it eliminates order as a
  confound when comparing candidate rubrics — at 2× Jev calls per pair.
- **F20** — F17 — **forward-run accuracy against a 3-outcome vocabulary (chance ≈ 33%)**:
  `location` 50%, `compensation` 58% (post-F4-fix), **`mission` 32% — at chance.** A
  stable reader whose output is unrelated to the operator's rulings is either a badly wrong
  rubric or a digest that doesn't carry the signal the operator is actually using; F15's
  "missing operator data, not wording" case is live here and unresolved.
- **F21** — operator — eligibility floor set at **70 usable pairs**, ratchetable either way
  once the loop proves useful. Supersedes the ~100 in F13. At 70: `location` (74) and
  `compensation` (64, marginal) qualify; `mission` (44) does not.
- **F22** — operator — the loop may **apply** candidate edits to `rubric.yaml` and iterate
  across several rounds unattended, forming theories from measured results; it may never
  **commit**. This is the operator's definition of autoresearch.
- **F23** — operator — **restore-on-crash is explicitly not required.** The operator will
  not run `./run` concurrently with a recalibration run and can notice and revert a dirty
  `rubric.yaml` before starting a session. No isolated rubric path, no crash-restore
  machinery; the loop mutates the working-tree rubric directly and leaves it for `git`.
- **F24** — operator, `67a04cb` — the hand-found `location` candidates (silence-on-travel
  reads as a penalty; location-pay language as a distributedness signal) were committed
  and then **deliberately reverted out of `rubric.yaml`**, on purpose, so the current
  committed text has no trace of them. This is a planted control: the loop's first run on
  `location` either rediscovers one or both from the backtest data alone, finds something
  else, or finds nothing — any of the three is evidence about the proposer, not just about
  `location`. The two candidates themselves live only here and in git history
  (`bbb6a14`'s parent), not in any file the loop reads.
