---
feature: digest-history
type: scouting
date: 2026-10-20
commit: 756fb40
---

## What We're Doing
Preserve digest history so judgment-time state survives assertion updates and later comparisons can refer to the digest version that was actually shown to the operator. Today the digest cache is current-state only; it overwrites by `(opening_id, target)` and deletes rows when assertions are backfilled, which means the historical digest that produced a comparison is not recoverable from the cache alone.

## Findings
- **F1** — `src/screen/digest/service.py:42-70` and `src/screen/store/repo.py:111-119,194-221` — the digest cache is a single row per `(opening_id, target)`. When assertions change, `delete_dimension_digests_for_opening()` deletes the cached row and the next read recomputes only the latest digest, so the system does not currently retain digest history.
- **F2** — `src/screen/types.py:216-223,231-235` and `src/screen/score/compare_picker.py:84-111` — `Comparison` already has `opening_a_digest_version` / `opening_b_digest_version`, and the pair picker already uses digest-version counts to decide whether a prior comparison is still settled. The schema is waiting for a versioned digest store.
- **F3** — live backtest / `scripts/backtest_jev_routing.py --show-mismatches` — some operator comparisons cannot be analyzed because one or both opening-target digests are missing. The missing rows cluster by target, which is consistent with cache invalidation/backfill gaps rather than a random data corruption event.
- **F4** — `docs/architecture/README.md:24-27`, `docs/architecture/decisions.md:350-358` — the repo already has one scoped exception to append-only state for the Jev classification backfill. Digest history needs its own explicit contract if we want historical comparison without losing the current cache behavior.
- **F5** — operator intent — we need to be able to ask, later, “what digest did the operator see when they made this comparison?” That requires keeping the old digest alongside the new one, not only the latest value.
