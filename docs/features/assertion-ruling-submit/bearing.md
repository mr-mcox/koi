---
feature: assertion-ruling-submit
type: bearing
date: 2026-08-29
commit: ac3bdb1dfde5ea8db6192904764db25247a869bd
branch: (detached, worktree bold-fig)
status: done
parent: ../review-ux/scouting.md
scouting: ../review-ux/scouting.md
---

## Problem

Once the assertion rating layout is honest and inspectable (`assertion-rating-layout`), the
operator needs to perturb the LLM's proposed fit per assertion and have that change the
score. This slice adds the write path: the override control, the `AssertionRuling` record,
and the Scorer's use of it.

## Done When

- [x] `AssertionRuling` type and table already exist from the layout leaf; this leaf adds
      the write path and Scorer override only (→ `assertion-rating-layout` Done When, scouting F25)
- [x] Each assertion row in the rating page has a one-click affordance to override its `fit`
      to any other `Fit` value (→ scouting F33)
- [x] Submitting an override writes or updates the `AssertionRuling` for that assertion and
      re-sorts the queue without a full page reload — HTMX partial swap, not a full-document
      GET (→ scouting F20, F31)
- [x] `score()` accepts an optional mapping/list of `AssertionRuling` and uses the operator's
      `fit` for rated assertions instead of the original assertion `fit` — test: overriding
      one assertion changes the score trace for its target
- [x] Existing JSON scoring routes (`/openings/{id}/score`, `/queue`) remain unchanged and
      still pass their tests

## Approach

- Sibling types, not a union — different payloads, different intents (→ scouting F25)
- One-click override per assertion: small buttons/dropdown for the other `Fit` labels, posted
  via HTMX, swapping the queue fragment and the assertion row's ruling display (→ scouting
  F20, F33)
- Scorer override is additive: `score()` takes an optional rulings parameter and substitutes
  the ruled `fit` for that assertion's original `fit` when computing `_target_stats`. No
  provenance model redesign yet (→ scouting F28, domain-model §Ruling open tension)
- DB write: upsert `AssertionRuling` by `(opening_id, assertion_id)` — repeated ratings
  replace the previous one, not append; the corpus is a calibration record, not an event log
- Keep JSON routes untouched; HTML route is the only consumer of the ruling store (→
  scouting F21)

## Not Doing

- `DimensionRuling` / continuous placement — deferred (→ scouting F25-F30)
- `PrecedentLookup` / RAG context injection — corpus too small (→ scouting F15)
- Provenance redesign — real open tension, premature until a corpus exists
- Raw click/position storage or calibration analytics — categorical ruling only
- Rating-VOI / triage — all assertions remain visible (→ scouting F3, F13)
- Batch generalization screen (D27) — retired prototype instrumentation (→ scouting F4)

## Testing

Test-first by default. Exempt:
- `src/screen/web/templates/rating.html` — Jinja template has no unit-testable logic of its
  own; behavior covered by route integration tests

## Recalibrate When

- The assertion-level UI needs to support a continuous placement too — `DimensionRuling` is
  no longer deferrable, and this surface must be redesigned (→ scouting F25-F30)
- The provenance model is redesigned so that `Assertion.provenance` is derived from the
  Ruling corpus — this bearing's scorer override becomes a placeholder, not the mechanism
- A JSON consumer needs to submit or read rulings — that would change the `/openings/{id}/score`
  or `/queue` contract

## Agreed

- `AssertionRuling` is a sibling type to future `DimensionRuling`, not a shared `Ruling` with
  a scope field (→ scouting F25)
- Categorical confirm/override only — no continuous fields or snap-to-bucket logic on
  assertion rating (→ scouting F28)
- HTMX partial queue update after submission — no full page reload (→ scouting F20)
