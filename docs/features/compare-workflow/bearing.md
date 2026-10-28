---
name: compare-workflow
type: bearing
date: 2026-10-28
commit: ef1f0d7
branch: main
status: orienting
scouting: ./scouting.md
---

## Problem

The compare workflow is too interruptive once Jev is already highly confident. The screen should stay uncluttered, keep the A/S/D shortcut path, and sample some high-confidence pairs back to the operator instead of showing every one.

## Done When

- [ ] The compare page renders without the Jev confidence banner, and the left/tie/right buttons still submit the same outcomes → covered by the compare page test
- [ ] A/S/D keypresses trigger the left/tie/right compare actions → covered by the compare page response markup
- [ ] `route_verdict()` samples auto-commit above threshold, with probability rising as confidence approaches 1.0, while sub-threshold verdicts still route to the operator → covered by routing unit tests with injected RNG

## Approach

- Keep the compare UI lean: no banner, no extra status chrome, just the preview and action path (→ scouting F1)
- Move the new sampling decision into routing so the template stays dumb and the operator-facing behavior is testable in isolation (→ scouting F2, F3)
- Use injected randomness in tests so the sampled routing is deterministic where needed (→ scouting F3)
