---
name: compare-workflow
type: scouting
date: 2026-10-28
commit: ef1f0d7
---

## What we're changing

The compare surface should be less interruptive: no tie-confidence banner, faster left/tie/right submission, and fewer forced reviews once Jev is already very confident.

## Findings

- **F1** — `src/screen/web/templates/compare.html:1-58` — the compare page is just a preview plus a three-button form, so the banner removal and A/S/D key handling belong in the template layer.
- **F2** — `src/screen/verdict/routing.py:35-81` — routing is still a hard gate: once a verdict clears threshold, it is either auto-committed or surfaced; there is no sampling step yet.
- **F3** — `scoring.yaml:78-92` — the current thresholds are operator-owned config, so any new auto-commit sampling policy should sit beside routing and be testable with injected randomness.
