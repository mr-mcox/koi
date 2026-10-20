# Shift Compare to Upside & Break Loops

**parent:** docs/architecture/README.md

## Approach
1. **Digest-Aware Exclusion (The Loop Fix):** In `compare_picker.py`, hard-exclude a pair/dimension if its latest comparison is an operator ruling AND the `opening_a_digest_version` / `opening_b_digest_version` match the current pool state. If the scraper finds new evidence (the digest changes), the pair becomes askable again.
2. **Kill Closeness (Stop Squabbling):** Remove the `closeness` multiplier from pair priority in `compare_picker.py`. Pit high-variance unknowns against relevant reference points rather than exclusively hunting for dead heats.
3. **Upside-Focused Boundary Weight:** Replace `p * (1 - p)` in `bandit.py` with a relevance function that doesn't collapse to zero for roles safely in the Top 5. The operator uses a fuzzy Top 5 to consider roles, so a role with `p=0.9` (likely inside) should remain relevant to ask about if its variance is still high, and roles with high upside but lower probability shouldn't be penalized as heavily as they were by the sharp `0.5` peak.
4. **Update `decisions.md`:** Amend S14 to record the failure of variance-decay for operator rulings (due to the `_latest_per_pair` loop) and the shift from boundary-squabbling to upside-discovery for the picker.

## Done When
-[x] Operator rulings are hard-excluded unless digest versions have changed.
-[x] `closeness` is removed from `compare_picker.py`.
-[x] `boundary_weight` is flattened to reflect upside rather than boundary squabbling.
-[x] `decisions.md` reflects the architectural shift.

## Not Doing
- We are not changing `top_k: 5`. The boundary is fuzzy, but 5 is the actual number the operator deals with. We're fixing the math's reaction to the boundary, not the boundary itself.
- We are not changing the core Laplace fit or Thurstone beta mechanics.
- We are not inventing a "minimum assertions" threshold; thin evidence is valid to evaluate.
