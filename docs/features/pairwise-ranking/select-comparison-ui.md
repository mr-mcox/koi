---
feature: pairwise-ranking
type: bearing
date: 2026-09-18
commit: 143a87d370ed31ea793e97b762d6894677e13c4b
branch: main
status: completed
parent: ./bearing.md
scouting: ./comparison-screen-scouting.md
---

## Problem

comparison-screen.md proved that manual pairwise comparisons move the live ranking. A
first pass wired the backend picker `select_comparison`
(`src/screen/score/compare_picker.py:170`) into `/compare` as a *default* — dropdowns
still let the operator override the pair/dimension, and the screen labeled the
suggestion ("Suggested comparison"). Operator feedback on that pass: the dropdowns and
labeling are unwanted surface. The screen should hand over a fully-decided comparison —
no picking, no "this is a suggestion" framing — and after judging, immediately hand over
the next one. Terrain: [comparison-screen-scouting.md](./comparison-screen-scouting.md),
`compare.md`.

## Done When

- [x] `GET /compare` renders only the picker's chosen pair/dimension preview — no
      selection dropdowns, no Show button, no "Suggested comparison" /
      "manual override" framing → `tests/test_web.py`
- [x] When the picker returns `None` (nothing left to compare), `/compare` renders a
      plain "nothing to compare right now" state with a link back to the queue → test
- [x] Submitting any outcome (Left wins / Tie / Right wins) redirects straight to the
      next `GET /compare` — the operator never has to reopen the page between
      judgments → test
- [x] The queue's "Compare" link continues to route to `/compare` (no new nav surface)
      → existing test coverage
- [x] Neither preview column names the company or opening being judged (e.g. "Acme —
      Staff Software Engineer") — only the dimension label and content render, so a
      judgment can't be swayed by recognizing who's on the screen → test

## Approach

- `suggest_next_comparison` (already in `src/screen/api/pool.py`) stays the single
  source of the pair/dimension; `/compare` GET no longer accepts `opening_a_id`,
  `opening_b_id`, `target` as operator-facing controls — it always asks the picker.
  (Existing internal helpers/tests may still call `_compare_target_context` directly
  with an explicit pair; that seam isn't operator-facing.)
- Remove `compare.html`'s `<form class="compare-form">` (three `<select>`s + Show
  button) and the `auto_suggested`/`no_suggestion` note copy entirely; the page is just
  the two-column preview plus the outcome-buttons form, or the empty state.
- `submit_comparison` (POST `/compare`) redirects to `/compare` instead of `/`
  (303) — landing back on the queue after every judgment was the old flow; now the
  screen re-suggests immediately. The queue is still one click away via "Back to
  queue".
- Empty state: `suggest_next_comparison` returning `None` renders a short message
  ("Nothing to compare right now.") and the "Back to queue" link, no preview, no forms.

## Not Doing

- Blinding anything beyond company/opening identity — assertion citations (source
  host/URL) still render, since they're evidence the operator may need to weigh, not
  identity.
- Auto-advancing skip/pass (a way to defer a pair without judging it) — not requested;
  add only if the operator asks for it.
- Exposing picker confidence or pair-selection explanation on the screen.
- Research-routing when the picker cannot find a pair — that is the picker's internal
  behavior and belongs to `research-targeting.md`.

## Testing

- Test-first by default. Exempt: nothing at this level.
- Replace the dropdown/manual-override assertions in `tests/test_web.py` with
  assertions against the no-selection, auto-advancing flow; keep the display-order and
  ruling-edit-redirect tests, adjusting their fixture setup to route through the
  no-param `/compare` (or call `_compare_target_context` directly, if it's more direct
  for pair-specific assertions) rather than query-param selection.

## Recalibrate When

- If `select_comparison` repeatedly suggests pairs the operator finds obviously
  settled, stop and escalate expected-information-gain selection (parent Not Doing,
  scouting F29).
- If losing the ability to target a specific pair makes debugging or fixture-driven
  testing painful, stop and add a non-operator-facing override (e.g. only reachable via
  explicit query params in tests, never linked from the UI).

## Agreed

- No dropdowns, no manual override, no suggestion framing — the picker's choice is the
  only path (→ operator, supersedes the "manual override stays" agreement below).
- Auto-advance to the next comparison after every judgment (→ operator).
- ~~Manual override stays; the picker is a default, not a constraint~~ — superseded by
  the agreement above (→ operator, scouting F15 no longer applies to this screen).
- Direct render, not redirect, for the GET path — keeps the URL simple (open space,
  carried over from the prior pass).
- Company/opening identity is hidden from the preview entirely, not just the
  selection UI — seeing "Acme — Staff Software Engineer" leaked information and
  invited a halo effect without making the judgment any easier (→ operator,
  corrects the Not Doing item from the first pass at this bearing).
