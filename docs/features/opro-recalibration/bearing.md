---
feature: opro-recalibration
type: bearing
date: 2026-10-22
commit: 327b05b
branch: main
status: orienting
scouting: ./scouting.md
---

## Problem

The recalibration loop can't learn yet. Every candidate lost to baseline, and the proposer
writes notes that Jev reads as rubric. It sees digests cut to 120 characters, and it gets no
memory of what earlier candidates changed. Make the measurement honest and the proposer
informed, then add OPRO-style history that a run can resume from, so a "no edit" result
means wording can't help, not that the loop couldn't see.
Terrain: [scouting.md](./scouting.md)

## Done When

- [x] Only rendered rubric text reaches Jev: the proposer's theory and expected effect never
      appear in the evaluated text → `test_render_candidate_text_keeps_heading_and_omits_proposer_reasoning`
- [x] An unchanged draft is byte-identical to the baseline, including the leading blank line
      the live renderer emits → `test_render_candidate_text_round_trips_the_live_rubric_text`.
      Unset proposal fields rehydrate from the current draft, so this holds by construction
      rather than by the model retyping text faithfully
      (**needs you**: a live `location` run to confirm a no-op lands inside the noise band)
- [x] The proposer sees full digests for every pair it is shown →
      `test_anthropic_proposer_shows_full_digests_and_maps_structured_output`
- [x] Offline Jev runs zero-shot on purpose, and "sure" is `route_verdict` auto-commit at
      the `scoring.yaml` thresholds → `test_evaluator_uses_zero_shot_and_live_thresholds`
- [x] Each run reports the noise floor (baseline evaluated twice) and, per candidate, a
      3×3 confusion matrix plus the fixed/broken pair counts against the current best →
      `test_confusion_matrix_and_bucket_counts_cover_all_outcomes`,
      `test_run_rounds_records_history_and_uses_paired_acceptance`
      (**needs you**: confirm the run log reads well on `location`)
- [x] Every round's proposer prompt carries the history of prior candidates (rubric draft,
      train score, fixed/broken pairs with full digests), and never any held-out result →
      `test_run_rounds_records_history_and_uses_paired_acceptance`
- [x] Each run writes the full transcript (candidate drafts, theories, expected effects,
      per-pair outcomes) to an untracked location → `test_record_round_advances_current_best_only_when_accepted`,
      `test_default_run_dir_is_namespaced_by_target_and_timestamp`
- [x] A run stopped at its round budget can be continued for N more rounds. It picks up
      from the same splits, baseline, noise floor, current best and history without
      re-measuring baseline → `test_save_and_load_round_trips_every_field`,
      `test_run_rounds_numbers_rounds_after_a_resume`
- [x] Resume refuses when the run's baseline rubric no longer matches `rubric.yaml` for the
      target → `test_resume_refuses_when_the_baseline_rubric_has_drifted`

## Approach

- The proposer is a BAML function returning a typed record: theory, a single
  `expected_effect` string, and **only the rubric fields it is changing**. Unset fields are
  rehydrated from the current draft by `render_candidate_text`, so an unedited field
  round-trips verbatim and a no-op proposal reproduces its input byte-for-byte
  (→ scouting F4, F5, F7, F36, F37, F38)
- One parser, `core.parse_rubric_fields`, both rehydrates partial proposals and splits a
  winning candidate for `apply_candidate`, so what lands in `rubric.yaml` is what was
  measured (→ scouting F6, F39)
- The evaluator reuses live's `route_verdict` and `scoring.yaml` thresholds instead of
  reimplementing them. Zero-shot and order-averaging are declared offline/live differences;
  the loop's "sure" shares live's definition, but it is not a prediction of live
  auto-commit precision (→ scouting F14, F15, F17, F28, F29)
- The run record lives in `src/screen/recalibration_run.py`, not the CLI: pinned splits,
  baseline text and counts, noise floor, and an append-only round log under the data dir.
  The OPRO history and the resume state are the same record, and it is unit-tested
  independent of the script (→ scouting F32–F34, F40)
- Acceptance is paired: a candidate replaces the current best only when fixed − broken
  exceeds the measured noise floor. The aggregate objective stays only as a tiebreaker
  (→ scouting F20, F21)
- History shows pairs that flipped as aggregate counts plus examples, framed as hints and
  not as gold. Held-out stays out of the prompt entirely (→ scouting F10, F18, F23)

## Not Doing

- TextGrad-style per-pair critique: the labels carry operator noise, so per-flip gradients
  would overfit it (→ scouting F24)
- GEPA's Pareto front and candidate merging: out of scope for now (→ scouting F25)
- Changing `_CLEAR_WINNER_CRITERIA` or the routing thresholds: those are live config. This
  feature only makes the loop measure against them (→ scouting F11, F14)
- Re-scoring against historical digest versions: measured first, acted on only if F22 fires
- Changing the live pool's few-shot policy: `few-shot-calibration` owns that

## Testing

Test-first by default. Exempt:
- `src/screen/baml_client/`: generated by BAML codegen
- the live BAML proposer adapter and the live Jev evaluator adapter: they call paid APIs.
  Covered by fakes via the existing `Proposer` / `Evaluator` protocols, as
  `jev_verdict_provider.py` is today

## Recalibrate When

- A no-op candidate still scores outside the noise band once rendered through the live path:
  Jev is format-sensitive in a way rendering doesn't fix, so stop (→ scouting F3)
- The noise floor is as large as typical candidate deltas: the loop cannot discriminate at
  this volume, and more rounds won't help
- An accepted edit makes live verdicts (which use few-shot) worse on the operator's next
  rulings: the zero-shot proxy is misleading for the verdict stage, so stop (→ scouting F28)
- More than ~10% of usable pairs have a latest digest that differs from the one the operator
  ruled on (→ scouting F22)
- The proposer's prompt with full digests and history no longer fits one call at 10 rounds

## Agreed

- Structured BAML output, not text-with-a-theory-comment: Jev must never read proposer
  reasoning (→ scouting F4, F7)
- Full digests, never truncated (→ scouting F8)
- Zero-shot Jev in the loop, not live few-shot: the rubric also feeds three stages that
  never see examples, and examples can stand in for wording. This also avoids the
  holdout plumbing (→ scouting F27, F28, F30)
- Resumable runs: a run on a good track can be extended without starting over
  (→ scouting F31)
- OPRO history with fixed/broken pairs, not TextGrad or GEPA (→ scouting F23–F25)
- A new feature, not a re-scope of `full-context-sonnet-baseline` (→ scouting F26)
