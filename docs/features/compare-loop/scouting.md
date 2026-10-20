# Compare Looping & Boundary Squabbling

The Compare UI repeatedly selects the same pair/dimension even after the operator has ruled on it, and wastes operator attention on dead heats at the exact Top 5 boundary instead of evaluating high-upside unknowns.

## Findings
1. **The Infinite Loop:** `_latest_per_pair` intentionally drops old operator rulings to keep only the newest. Because one ruling provides the exact same variance drop as a newer identical ruling, the variance stays static. The picker recalculates priority, sees the exact same high score, and asks the operator again indefinitely.
2. **The "Dead Heat" Trap:** `src/screen/score/compare_picker.py` computes `closeness = 0.5 - abs(_p_a_gt_b - 0.5)` and multiplies pair priority by it. This mathematically forces the system to seek tied pairs and structurally refuses to test high-variance unknowns against stable, known baselines.
3. **The Boundary Peak:** `boundary_weight = p_top_k * (1 - p_top_k)` maximizes at exactly `P=0.5`. It treats the Top-K cutoff as a strict sorting problem, aggressively penalizing anything not directly fighting for the #5 spot. The operator actually treats Top 5-10 as a fuzzy strategic pool and wants to surface upside, not micro-sort the exact boundary line.
