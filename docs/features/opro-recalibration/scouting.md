---
feature: opro-recalibration
type: scouting
date: 2026-10-22
commit: 327b05b
---

## What We're Doing

The recalibration loop (`scripts/recalibrate_rubric.py`) shows no signs of life: a 10-round
full-context run on `location` produced no candidate that beat baseline. The operator wants
to make the loop able to learn before asking whether rubric wording can learn at all:

- Structured proposer output (BAML) that separates the **theory**, **what metric it expects
  to move**, and the **rubric draft** — so nothing but rubric text ever reaches Jev.
- Fix the missing context — "trimming is stupid."
- Run Jev **authentically**, the way the live loop runs it (few-shot included).
- Then the OPRO direction: the proposer sees prior candidates, their scores, and what moved
  (which pairs flipped toward the operator and what offset them).

TextGrad-style per-pair critique is interesting but the labels are not golden — "there is
some operator noise where I may not score the same way a day apart." GEPA is out of scope
for now.

## Findings

### Run being diagnosed (operator, 2026-10-22, `location`, `--context-mode full --rounds 10`)

- **F1** — operator run log — baseline train **49/82 right** (17 sure + 32 unsure). All ten
  candidates scored **37–45 right**, every one below baseline; one SD of the right-count at
  n=82, p≈0.6 is ≈4.4 pairs, so the drop (~11 pairs in most rounds) is ~2.5 SD. Every
  candidate also moved mass from unsure → sure regardless of content.
- **F2** — operator run log — six rounds report `(no theory stated)` and three of them land
  on **identical** buckets (26/12/26/18). The theory parser only matches a first line
  starting `# theory:` (`src/screen/recalibration.py:221-228`); identical results across
  rounds suggest near-identical candidate text — plausibly the unchanged rubric wrapped in a
  preamble or fence. **Unverified: candidate text is never logged** (`run_rounds` stores it
  in `RoundResult.candidate_rubric_text` but the CLI never prints or persists it,
  `scripts/recalibrate_rubric.py:383-389`).
- **F3** [!] — F1 + F2 — if a near-unchanged rubric loses ~11 pairs, the search has been
  measuring **formatting sensitivity**, not wording. Cheap discriminating test: evaluate the
  baseline rubric with a `# theory:` line prepended. → §Recalibrate When

### What reaches Jev

- **F4** — `src/screen/recalibration.py:218-219` — the raw proposer output, including the
  `# theory:` line and any preamble, is passed straight to `evaluator.evaluate(…, candidate)`.
  The theory sentence is read by Jev as rubric. Rounds 5–6 (the only ones that moved
  precision-when-sure) are the ones whose theory line instructs "call these ties."
- **F5** — `scripts/recalibrate_rubric.py:213-262` — the text-parsing path
  (`_candidate_body_lines`, `_parse_fit_anchor_lines`, `_parse_dimension_candidate`) exists
  only to turn free text back into `definition` / `fit_anchors` / `look_for` for
  `apply_candidate`. It runs only for the winner, so a malformed candidate is evaluated
  anyway and fails only at apply time.
- **F6** — `src/screen/extract/prompt.py:28,49-57,97-104` — `_render_one_dimension(dim)` renders
  a dimension dict (`label`, `slug`, `weight`, `definition`, `fit_anchors`, `look_for`) into
  exactly the text Jev sees live; `rubric_text_for_dimension` then applies
  `_resolve_private`. A structured candidate rendered through the same function is
  byte-for-byte the live shape.
- **F7** — `src/screen/baml_src/clients.baml:1-40`, `src/screen/digest/baml_digester.py`,
  `src/screen/extract/baml_extractor.py` — BAML is the house structured-output path
  (architecture README: "No agent framework. BAML covers structured output"). An
  `Anthropic` client exists (currently pinned to Haiku). The proposer currently bypasses
  BAML with a raw `anthropic.Anthropic()` call (`scripts/recalibrate_rubric.py:85-129`).

### Missing context

- **F8** — `scripts/recalibrate_rubric.py:140-147` — every case shown to the proposer is
  `digest_a[:120]` / `digest_b[:120]`. "Full" mode (`:149-150`) only lifts the *count* limit.
  Round 5's theory compares "remote-first, occasional travel/offsites" with an identical
  string — the differentiating evidence was truncated away.
- **F9** — `scripts/recalibrate_rubric.py:334`, `src/screen/recalibration.py:209-213` —
  `labeled_cases` is computed once against the baseline rubric and reused every round;
  after an accepted candidate the proposer still sees baseline mismatches.
- **F10** — `scripts/recalibrate_rubric.py:107-112` — prior rounds show only the theory and
  the **held-out** buckets: no candidate text, no train score, no per-pair outcomes. Showing
  held-out results to the proposer leaks the held-out set into selection pressure.
- **F11** — `src/screen/recalibration.py:62-84` — `BucketCounts` collapses errors to
  right/wrong × sure/unsure. It cannot distinguish tie-vs-winner errors from A-vs-B errors.
  Tie decisions are driven by `_CLEAR_WINNER_CRITERIA`
  (`src/screen/verdict/jev_verdict_provider.py:18-21`), a fixed prompt outside the rubric,
  so a rubric edit may have little purchase on that class of error.

### Jev authenticity

- **F12** — `src/screen/api/pool.py:158-176,198-213`, `scoring.yaml:81` — the live loop passes
  **12 few-shot examples** sampled at random from the operator's own rulings on the target
  (`few_shot_examples_from_rulings`, `src/screen/verdict/few_shot.py:14-37`).
- **F13** — `scripts/recalibrate_rubric.py:52-53,177-178` and
  `scripts/backtest_jev_routing.py:117` — both offline harnesses call `get_ruling(…, [])`:
  **zero few-shot**. The recalibration loop measures a configuration production never runs.
- **F14** — `src/screen/verdict/routing.py:35-80`, `scoring.yaml:74-75` — live "sure" means
  `route_verdict` auto-commits: tie when `1 - p_clear ≥ 0.95`, winner when `p_clear ≥ 0.85`
  and winner-confidence ≥ 0.85. The loop invents its own rule instead
  (`scripts/recalibrate_rubric.py:35-44`: tie if `p_clear < 0.5`, sure if a product ≥ 0.70).
  Its "precision-when-sure" is not the live auto-commit precision.
- **F15** — `docs/features/rubric-recalibration/scouting.md` F10 — the earlier scouting
  already said the loop should be a consumer of the backtest's `route_verdict` path, not a
  reimplementation. F14 is drift from that.
- **F16** — `src/screen/verdict/few_shot.py:31-37`, F12 — few-shot examples are drawn from
  the same operator rulings the loop scores against. Offline, the pair under evaluation and
  every held-out pair must be excluded from the pool, or the score leaks labels. The draw is
  random per call; unless the per-pair draw is fixed across candidates, the few-shot sample
  becomes a noise source in candidate-vs-candidate comparison.
- **F17** — `docs/features/rubric-recalibration/scouting.md` F17-F19 — order-averaging (run
  fwd + swapped) is already established as cheap and bias-removing; the loop does this
  (`scripts/recalibrate_rubric.py:52-56`). Live does not average — a known, accepted
  offline/live difference.

### Noise and power

- **F18** — operator — rulings are not a golden dataset: the operator may not score the same
  pair the same way a day apart. This bounds attainable accuracy and argues against
  optimizing individual flips (the TextGrad hazard).
- **F19** — `docs/features/rubric-recalibration/scouting.md` F9 — search over clause edits at
  this volume optimizes sampling noise; "propose a small number of candidates, measure,
  report." A 10-round sequential loop selecting the best on train is already mild search.
- **F20** — `scripts/recalibrate_rubric.py:334-337` — the baseline is evaluated twice
  (`_build_labeled_cases` and `evaluator.evaluate`) on identical inputs; the two results
  are discarded rather than compared. Comparing them is a free Jev run-to-run noise
  measurement.
- **F21** — `src/screen/recalibration.py:117-124,246-257` — acceptance is a lexicographic
  objective on aggregate counts; a candidate that fixes 6 and breaks 5 is indistinguishable
  from one that fixes 1 and breaks 0. A paired per-pair comparison (fixed vs broke, McNemar)
  uses the same data with more power.

### Label provenance

- **F22** [!] — `src/screen/recalibration.py:147-149`, `src/screen/store/repo.py:171-191`,
  `src/screen/store/migrations/0010_create_comparisons.sql:15-16` — `load_pairs` uses the
  *latest* digest per opening, not the `opening_*_digest_version` the operator saw when
  ruling. If digests were regenerated after a ruling, the label describes text Jev never
  sees. Extent unmeasured. → §Recalibrate When

### Approach (prior art the operator chose among)

- **F23** — operator — OPRO is the chosen direction: the meta-prompt carries the trajectory
  of prior candidates with their scores. Operator addition: show what moved — the pairs that
  flipped toward the operator, and what offset them.
- **F24** [x] — operator — TextGrad-style per-pair critique deferred: labels carry operator
  noise (F18). → §Not Doing
- **F25** [x] — operator — GEPA (per-instance Pareto front, candidate merge) out of scope for
  now. → §Not Doing
- **F26** [x] — operator — this is a new feature with its own scout and bearing, not a
  re-scope of `full-context-sonnet-baseline`. → this document

### Few-shot revisited (operator pushback, 2026-10-22)

- **F27** — operator — the goal is a better **rubric**; holding out the exact pair from a
  few-shot pool adds complexity and cost, small as it is. Is live-style few-shot worth it?
- **F28** — `src/screen/research/batch.py:175`, `src/screen/intake/cli.py:41,70`,
  `src/screen/verdict/jev_assertion_classifier.py:59` — the rubric text feeds research,
  extraction and assertion classification, **none of which use few-shot**. Only pairwise
  verdicting (`src/screen/api/pool.py:202`) does. Zero-shot verdict accuracy is the closer
  proxy for how the rubric performs everywhere else; few-shot accuracy measures
  rubric + examples together, and the examples can mask or substitute for wording (the
  prototype found remediation was `example-only` on 7/7, `docs/architecture/learnings.md:102-119`).
- **F29** — F28 — consequence: under zero-shot the loop's "sure" cannot equal live
  auto-commit precision whatever thresholds it uses, because few-shot shifts Jev's
  calibration. Routing through `route_verdict` keeps the definition of "sure" shared with live
  code. It does not make the number a live prediction.
- **F30** [x] — F27, F28 — few-shot stays out of the optimization loop, a declared
  offline/live difference; F12–F13 stand as findings, F16 no longer applies. → §Agreed

### Resumability (operator, 2026-10-22)

- **F31** — operator — if a run is on a good track when it hits its round budget, the
  operator wants to continue it for a few more rounds rather than start over.
- **F32** — `src/screen/recalibration.py:198-237` — the only state `run_rounds` carries
  between rounds is `rounds` (the history), `rubric_text` (current best) and
  `best_train_score`. The OPRO history *is* the run state, so persisting history already gets
  most of resume for free.
- **F33** — `src/screen/recalibration.py:132-176`, `scripts/recalibrate_rubric.py:322-337` —
  what resume must pin and not recompute: the pair ids in each split (new operator
  rulings since the run started would otherwise change the split for the same seed), the
  baseline rubric text, the baseline counts and noise floor (re-measuring costs Jev calls
  and moves the reference point), and per-pair outcomes for the current best (the input to
  fixed/broken).
- **F34** — `.gitignore:9` — `data/` is gitignored; a run directory under the data dir
  stays untracked and inside the privacy boundary (transcripts quote digests).
- **F35** — operator — bearing length over 80 lines is fine for now.

### Shape corrections (operator, during implementation)

- **F36** — operator — `metric` + `direction` were two fields for one thought; a single
  `expected_effect` string carries "what moves and which way" without inviting the model to
  split a sentence across two slots.
- **F37** — operator — every rubric field on the proposal is now optional. A field left
  unset means "not editing this" and is rehydrated from the current draft, so the proposer
  never retypes text it didn't mean to change. This also makes the no-op candidate
  byte-identical to its input by construction rather than by the model's transcription
  fidelity — directly retiring the F3 hazard.
- **F38** — `src/screen/extract/prompt.py:50` — `rubric_text_for_dimension` output **begins
  with a blank line** (`_render_one_dimension` leads with `\n### `). Any render that
  normalizes it away makes every candidate differ from baseline by a leading newline.
  Pinned by a round-trip test against the live `location` text.
- **F39** — the CLI had grown a second rubric parser (`_parse_dimension_candidate`,
  `_parse_fit_anchor_lines`) beside the rehydration parser — two readers of one format,
  free to drift. Collapsed onto `core.parse_rubric_fields`; `apply_candidate` now writes
  back exactly what was measured.
- **F40** — operator — run persistence does not belong in the CLI script. Moved to
  `src/screen/recalibration_run.py`, where it is directly testable; the script keeps only
  live adapters and glue.
