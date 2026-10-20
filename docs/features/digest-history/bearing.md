---
feature: digest-history
type: bearing
date: 2026-10-20
commit: 756fb40
parent: ./scouting.md
status: done
---

## Problem
We need historical digest visibility, not just the latest cache entry, so we can reconstruct what the operator saw at judgment time and preserve comparison provenance across later assertion updates. The current `dimension_digests` table is a replace-in-place cache keyed by `(opening_id, target)`; that is enough for the live view, but not enough for historical comparison or durable digest-version references.

## Done When
- [x] Every recomputed digest gets a durable version identifier instead of replacing the prior record in place.
- [x] `Comparison.opening_a_digest_version` / `opening_b_digest_version` are populated from the version actually shown at judgment time.
- [x] The current digest remains easy to read for the live UI, but old digests stay queryable for audit/historical comparison.
- [x] Backfill / assertion-update flows no longer erase the only record of a prior digest.
- [x] Tests cover both the latest-digest read path and a historical lookup path.

## Approach
1. Split the current digest-cache concern from the historical record concern: keep the live read path fast, but store each recomputation as a versioned digest record rather than overwriting the only row.
2. Thread digest-version identifiers through the comparison write path so operator rulings and provisional comparisons can point back to the digest they were made against.
3. Preserve the current “show the latest digest” behavior at the UI boundary; history is additive, not a change to the operator-facing surface.
4. Treat assertion backfill as a source of new digest versions, not as a destructive cache cleanup.

## Not Doing
- Reworking scoring or comparison semantics as part of this feature.
- Dropping the current cache behavior before a versioned replacement exists.
- Making digest history a generic event log for everything; this is only for dimension digests and the provenance needed to explain comparisons.
- Staging a broad migration of existing historical comparisons beyond what is needed to preserve and reference digest versions.

## Testing
- A direct unit test for “write a digest twice for the same `(opening_id, target)` and keep both versions.”
- A test that confirms the live lookup still returns the latest digest.
- A test that comparison records capture the digest version used at judgment time.
- A smoke run of `scripts/backtest_jev_routing.py --show-mismatches` after a backfill or recomputation to verify the historical trail still exists.

## Recalibrate When
- The versioned-store shape makes digest lookup too awkward for the live UI.
- The historical trail is useful, but comparison versioning needs a different granularity than one digest version per opening/target.
- Backfill volume is large enough that a two-table history/current split is a better fit than a single append-only table.

## Agreed
- Keep the live digest view, but make digest history durable.
- The current cache row is not sufficient evidence once comparisons need to refer back to what the operator actually saw.
- When the implementation lands, the existing `Comparison` version fields should start carrying real values instead of remaining placeholders.
