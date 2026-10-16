# Scouting: Jev Assertion Classification and Confidence

## Problem Statement
Currently, assertions are extracted and scored (`Poor`/`Mixed`/`Strong`) in a single BAML pass. This has two flaws:
1. It conflates finding a claim with evaluating it.
2. It destroys the model's internal confidence signal. The Monte Carlo scorer assigns uncertainty (variance) strictly based on assertion *count*—treating an ambiguous 52%-confidence `Mixed` claim with the exact same mathematical weight as an ironclad 97%-confidence `Strong` claim.

## Findings
- **F1 (Jev Calibration):** A codemode run against existing assertions demonstrated that Jev's `models.classify()` accurately reproduces operator intent when given strict rubric anchors, and crucially, its confidence scores track human ambiguity (e.g., 97% for clear hits, 50-60% for muddy/ambiguous quotes).
- **F2 (Rubric Alignment Prerequisite):** We discovered and fixed a drift in `craft_direction` where the top-level definition was vague while the anchors were strict. Jev is highly literal; for it to score accurately, the definition and anchors must carry the same constraints.
- **F3 (BAML Runtime):** The production pipeline passes the `rubric.yaml` text dynamically to BAML at runtime, meaning rubric edits take effect in the existing extraction pipeline without code changes.
- **F4 (Relevance vs. fit):** Jev can separate relevance from fit. Generic fragments like "United States" for `location` or "GitLab values transparency" for `craft_direction` are irrelevant and should be dropped, while concrete but wrong-discipline passages (e.g. backend/system-integration stacks for `craft_direction`) are relevant and scored `Poor`.

## Next Steps (To be resolved in Bearing)
We need to decouple extraction from classification. BAML should just extract claims (target, quote, citations). Jev should then classify those claims against the rubric and return both a relevance judgment and a `Fit` + `Confidence`. This confidence score must then route into the SQLite database and ultimately replace/scale the fixed variance prior in the `Pool` scorer. We should also backfill the live, non-archived opportunity set so the active pool reflects the new filter and scoring shape.