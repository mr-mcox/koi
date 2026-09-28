---
feature: comparison-similarity-kernel
type: scouting
date: 2026-09-28
status: implementing
scouting_for: ./bearing.md
---

## What we're pivoting to

The bearing as written commits to an **offline** similarity kernel: embed the digests, cosine > τ, generate provisional ties, store them, let the fit consume them. The live pool showed that machinery works (dedup, per-provenance beta, picker suppression, fastembed) but the **gate signal is wrong**: digest-cosine catches near-duplicate *text*, not rubric-semantic similarity. Your actual goal is to suppress attention on openings that are *rubrically* similar (you'd judge them similarly on the dimension), and digest-cosine is a crude proxy that misses those — the live pool's top cosine pair ("staff software engineer, remote US" roles at different companies) is **0.883**, similar-but-not-near-identical, and at τ=0.85 the kernel fires ~11 provisional ties pool-wide, mostly **not** in your ruling corpus.

The pivot: gate on **rubric-similarity** (would the rubric score these similarly?), produced **live by Jev** per comparison in the flow — Jev as a short-circuit before the operator sees a comparison, auto-tie where Jev is confident, escalate where uncertain.

## Findings

- **F-SC1 · Jev API shape** — `typesafe-sdk`, `TypeSafeClient`, `POST /v1/systemone`, model `jev-1.13.0` / alias `jev-latest`. Three question types: `Choice` (pick from options + per-option probabilities + confidence), `Score` (rate against ordered rubric levels + weighted score + confidence), `Noul` (yes/no + probability). Confidence is in `provider_details['confidence']` (0–1). **No temperature parameter** — "Jev has no sampling knobs, so the generic `temperature`, `top_p` are ignored." Batching supported: "multiple questions can share one state and be evaluated in a single request," "all questions evaluated in parallel." `typesafe_tool_call_threshold` sets how sure Jev must be before it takes a tool. Context 64k tokens/request (32k for state + longest question). Rate limits 1,200 RPM / 250k tokens/s, may change without notice. → web search
- **F-SC2 · Cost/latency/dependenty** — published $0.042/M input tokens (output free), 70–500ms end-to-end per call. Arithmetic: 10k tokens ⇒ $0.0004/call; 1B tokens ⇒ $42. Per-comparison cost ~$0.0004 (assuming ~10k tokens/prompt). Per-comparison latency: the 70–500ms is a **batched** end-to-end figure; per-single-comparison latency is not separately published and may be higher (the batched call amortizes network setup, a single call can't). → web search (confirmed the batched figure; single-call latency still unverified)
- **F-SC3 · Two-stage fit against the live pool** — read-only `data/live/screen.db` (no mutation, `?mode=ro` URI): 57 screening openings, 63 carry a `location` digest. Pairwise cosine among the 63: **1 pair** exceeds τ=0.85 (top cosine 0.883, two "staff software engineer" remote-US roles at different companies); next 0.831, 0.782. So at τ=0.85 the coarse gate (fastembed cosine > τ) passes **~11 candidates** to Jev per read; at τ=0.90, ~3. Jev supports batching → the ~11 candidates for a read can be **one batched call** ⇒ ~70–500ms/read (not 11 ×). The coarse gate (fastembed, local ONNX, embeddings cached after one-time warm) adds ~ms per read; the Jev fine gate adds ~70–500ms/read. **Total ≈ 0.5–0.8s/read** — a regression vs the current flow (~instant render → operator click), ~250–500× faster than full-Jev (3,249 × 70–500ms ≈ 200–2500s/read). → live-pool read-only + Jev batching docs
- **F-SC4 · Win-propagation scope** — you want provisional **wins** (direct, not chained): "C is definitely better than D" when "A is better than B" and A≈C and B≈D is **not** auto-inferred; each pair's win is a direct Jev judgment. Consistent with F9 ("provisional comparisons" are verdict-bearing, including wins) and the Not Doing ("trusting *without override*") **if** auto-tie-win is scoped to pairs without an existing operator ruling (new pair, nothing to override yet) and existing pairs are validated/overrideable. But it's a bigger step than tie-only, and it's your bearing to revise, not a silent change on my end. → operator (this conversation)
- **F-SC5 · Few-shot is the default** — "while I have a rubric, there may be nuance that's not yet captured in there that is signal for Jev to calibrate on." Few-shot examples carry the rubric-nuance beyond the rubric text; the operator provides the examples (their rulings + divergent cases), so they calibrate Jev. The examples determine the unanimous-vs-uncertain split, which determines the latency hit (unanimous → skiped, operator no wait; uncertain → operator sees, Jev wait). → operator (this conversation)
- **F-SC6 · Criterion 4 testability under the Jev gate** — location's weight-6 is handled by Jev's confidence naturally: high confidence (strong similarity) → auto-tie; low (weak) → bubbles to operator. So criterion 4 **becomes testable in the new design** in a way the offline cosine gate couldn't deliver (1 tie didn't suppress; ~18 openings/153 ties did) — *if* Jev calibrates right (few-shot). The live pool's ~11 near-duplicate pairs at τ=0.85 is the calibration target. → live-pool read-only + analysis (this conversation)
- **F-SC7 · What's unwinding before the pivot** — (a) the stale `test_provisional_tie_suppresses_location_in_picker` test (tested the offline cosine gate the pivot retires; it fails: 1 tie doesn't suppress `location`'s weight-6); (b) the offline tie-generation (`provisional_ties()` kernel in `src/screen/score/simularity.py`); (c) the "generate when digests update" trigger (Approach bullet 2's first clause); (d) the offline storage of pre-computed provisional ties; (e) the `comparison_beta` operator-owned per-provenance dial → `jev_confidence_threshold` operator-owned confidence dial (swap, not pure unwinding — Jev owns its beta internally, so the operator loses that dial unless you wind a new `jev_confidence_threshold`). All four are the offline-generation pieces the Jev-pivot retires. → this conversation + bearing analysis

## What stays (Jev-orthogonal, survives the pivot)

- Dedup-to-latest + auto-tie displacement (F18) — the reduction mechanism
- Per-provenance `w(s)` weight (F10iii) — the weighting mechanism
- `provenance` column + migration 0012 + mapper + repo INSERT — storage round-trips
- fastembed + ONNX (F14) — the embedder (now the coarse-stage embedder)
- Embedding cache + staleness-keying (Approach bullet 1)
- Picker suppression emergent (F19) — the mechanism
- `simularity_s0` config — stays (coarse gate uses it)

## Open decisions (yours, not mine)

1. **Win-propagation scope** — confirmed (wins, direct not chained), but it's a bigger step than tie-only and revises the bearing. Your call.
2. **Zero-shot vs few-shot** — few-shot is your default; few-shot examples calibrate Jev to rubric nuance. The examples determine the unanimous-vs-uncertain split, which determines the latency hit.
3. **The latency regression** — two-stage gate ≈ 0.5–0.8s/read vs current (~instant). You said "not concerned about dep weight" but ARE concerned about "save me time" — the latency threatens that. Jev batching (~one call/read) mitigates but doesn't eliminate it. Your call whether ~0.5–0.8s/read is acceptable.
