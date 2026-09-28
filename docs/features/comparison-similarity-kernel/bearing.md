---
feature: comparison-similarity-kernel
type: bearing
date: 2026-09-28
commit: 402a3f286c873de77b6a980f2fa846004bbbf965
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

The operator's comparison attention is being spent on near-duplicate dimension pairs — back-to-back `location` comparisons across different companies whose digests all say "US remote full-time" — instead of on novel, judgment-heavy dimensions. `location` is opening-level, so two different companies' near-identical remote postings get zero correlation today; the picker surfaces them as high-variance because nothing tells it they're analogous. The operator wants previous rulings to carry forward so comparison energy goes where it's novel. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] For two openings whose digests would be **rubrically similar** on `location` (the rubric would score them similarly), Jev rules `location` left/right/tie with confidence; for rubrically-different openings, **none** → `tests/test_similarity_ties.py` over a fake embedder + few-shot examples carrying rubric nuance (Done When criterion 1 — pivoted to a two-stage Jev gate)
- [ ] A provisional **win** or tie and an operator ruling on the same pair produce a different posterior than two operator rulings — provisional weighs less, via per-provenance beta. A provisional **win** (Jev confident → auto-tie, direct) is a bigger step than tie-only; the Not Doing rules out *blind* trust, but F9 anticipated provisional comparisons and auto-tie-with-override is consistent **if** scoped to new pairs (no existing ruling → nothing to override yet). Existing pairs: operator validates/overrides. → `tests/test_compare.py`
- [x] The fit reduces to the latest judgment per (unordered pair, dimension): a provisional win/tie then an operator ruling on the same pair yields the operator-ruling-only result, not the sum of both (closes F18) → `tests/test_compare.py`
- [x] An explicit operator comparison on a same-company company-level dimension displaces the auto-tie for that pair — the fit equals the different-company fit (no coexisting tie term), not a win+tie blend (folded into F18's dedup; operator-approved during implementation) → `tests/test_compare.py`
- [ ] With two near-duplicate openings tied on `location` and another dimension carrying higher unresolved variance, `suggest_next_comparison` does not return `location` for that pair — **emergent from the Jev verdict raising `cov[a][b]`** (Done When criterion 4 — pivoted to Jev confidence gate; testable *if* Jev calibrates right) → `tests/test_compare_picker.py`
- [ ] A `decisions.md` entry places provisional **similarity ties and wins** on the `precedent_matched` rung, naming what it rules out (auto-closing-without-override is out; auto-tie-win-with-override is in if scoped to new pairs) → `grep` over `docs/architecture/decisions.md`
- [ ] The live `/compare` flow no longer repeatedly offers near-duplicate `location` pairs; the picker surfaces novel dimensions instead — via Jev short-circuit (auto-tie where confident, escalate where uncertain) → **needs you**: run `/compare` on the live pool and confirm

## Approach

- Embed the existing per-`(opening, target)` dimension digest (`dimension_digests`) with `fastembed` + `all-MiniLM-L6-v2` ONNX — no torch; same 384-dim model the operator attests worked in logseq-navigator, via ONNX Runtime. Embeddings cached and staleness-keyed by the digest's assertion count, mirroring `digest/service.py` (→ scouting F6, F14). **Coarse-stage embedder — the offline kernel's embedder, repurposed as the bulk pre-filter.**
- Per-dimension, same-dimension only, for **every scored dimension** (including `domain`): for each opening pair whose digests would be **rubrically similar** (the rubric would score them similarly), Jev rules that pair `left/right/tie` with confidence; for rubrically-different openings, **none**. `w(s) = clamp((s − s₀)/(1 − s₀), 0, 1)` is the per-pair weight Jev applies to its verdict. τ and s₀ are operator-owned config values, not constants. On `domain` the tie correlates *factual* domain similarity; the operator's coolness judgment stays the load-bearing signal, never guessed by the tie (→ scouting F10, F11, F20, F21). **Fine-stage gate — Jev's calibrated confidence is the gate.**
- Provisional verdicts are produced **live by Jev** per comparison in the flow — Jev as a short-circuit before the operator sees a comparison. `fit_pairwise` is no longer called with a pre-computed tie list; the fit consumes Jev's verdict + confidence directly. An operator ruling displaces a provisional verdict on that pair — "until I override" is literal, not a weight competition (→ scouting F15α, F18). **Live generation — the offline kernel is retired.**
- Picker suppression is emergent, not a separate layer: provisional verdicts raise `cov[a][b]`, lowering `dim_var_diff` for the similar dimension, so `_best_dimension_for_pair` naturally moves to the higher-variance dimension. No new picker ranking code (→ scouting F19)
- A `decisions.md` entry records provisional **similarity ties and wins** on the `precedent_matched` rung, naming what it rules out (auto-closing-without-override is out; auto-tie-win-with-override is in if scoped to new pairs) (→ scouting F8, W5)

## Not Doing

- Cross-dimension similarity — a `location`-similar pair is not evidence of a `mission`- or `comp`-similar pair; whole-posting-duplicate dedup is an intake concern, not scored here (→ scouting F11, F20)
- A separate picker-suppression layer — suppression falls out of provisional-verdict injection via `dim_var_diff` (→ scouting F19)
- Auto-closing judgments / trusting provisional verdicts without override — agreement-rate measurement (OQ6) and any auto-close argument are deferred until a real corpus exists (→ scouting F8, W5, OQ6). **Auto-tie-win is in for new pairs (no override needed yet); existing pairs are validated/overrideable — consistent, not a violation.**
- `PrecedentLookup` (auto-filling assertions on unexamined dimensions) — this fabricates comparison ties between evidenced openings, not assertions on unexamined ones (→ scouting F9)
- A pool-wide covariance kernel inside `rank_pool` (O(n²) per read) — provisional verdicts inject at the comparison layer, not as a live scorer kernel (→ scouting F12, F13)

## Testing

Test-first by default. Exempt:
- `src/screen/embed/fastembed_embedder.py` (live adapter) — calls a local model runtime; unit tests inject a fake embedder via a Protocol, mirroring the `baml_digester`/`baml_extractor` exemption
- The live Jev adapter (`src/screen/embed/jev_adapter.py` or similar) — calls the TypeSafe API; unit tests inject a fake verdict layer via the `Embedder`/verdict Protocol. **New exemption — the live Jev adapter is the new live-adapter exempt file.**

## Recalibrate When

- If provisional ties flatten the live queue (rank bands collapse, too many openings tied together), stop — τ or s₀ is too low; re-tune rather than ship the flattening
- If `fastembed`'s similarity on real digests doesn't separate near-duplicates from merely-similar pairs (no clean threshold), stop — the model is too coarse for this text; reconsider the embedder
- If the dedup-to-latest step (F18) changes live rank order for pairs with multiple *operator* re-judgments, stop — check whether re-judgments were meant to accumulate or replace before relying on the new behavior
- If an operator override needs to propagate through the similarity graph (ruling on A~B should weaken A~C), stop — that's divergence-propagation, out of scope here; decide whether to expand
- If `fastembed`/onnxruntime pulls a transitive dep that breaks the discipline gates or the feather-light dep budget, stop; reconsider the embedder choice. **Jev is a paid external API — the dep-budget concern you said you're not concerned about, but the latency (70–500ms/read) is a real "save me time" concern.**
- If the two-stage Jev gate adds ~0.5–0.8s/read latency vs the current flow (~instant), stop — the latency threatens the feature's purpose. Jev batching (~one call/read) mitigates but doesn't eliminate it. **Decide whether ~0.5–0.8s/read is acceptable.**

## Agreed

- `fastembed` + all-MiniLM-L6-v2 ONNX, not sentence-transformers/torch — torch's hundreds-of-MB weight is disqualifying for a feather-light project (→ scouting F14, F17)
- F10iii threshold + graded-above-threshold, not a cliff (i) and not threshold-free grading (ii) — boilerplate clusters hard at the top, vague similarity shouldn't count (→ scouting F10)
- F15α per-comparison provenance column + dedup-to-latest, not on-the-fly generation (β) — "until I override" is literal displacement, and the dedup closes a gap the docstrings already claim (→ scouting F15, F18). **Revised: `comparison_beta` (operator-owned per-provenance dial) → `jev_confidence_threshold` (operator-owned confidence dial). Jev owns its beta internally; the operator owns the gate value, not the beta — measure-before-model preserved.**
- Same-dimension only, not cross-dimension — a location-similar pair is not evidence of a mission/comp-similar pair (→ scouting F11, F20)
- Settledness is the existing rank-band width, not a new workflow state — narrow band = more settled (→ scouting F16)
- Provisional ties carry less weight than operator rulings — "doesn't need too much weight" (→ scouting F9, F15)
