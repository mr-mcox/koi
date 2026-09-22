---
feature: pairwise-ranking
type: scouting
date: 2026-09-17
commit: c17db8e
parent: ./bearing.md
---

## What We're Doing

bearing.md's second Done When item — "pairwise comparisons by the operator move the
ranking" — has its backend half done (compare.md: storage, batch fit, auto-tie, picker,
calibration log). compare.md's own Not Doing named what's left: "the comparison screen,
its route, and end-to-end web tests — a later bearing." This scouts that later bearing:
what exists to reuse, what's genuinely missing, and where it plugs into the pool scorer.

## Findings

- **F1** — `src/screen/score/compare_picker.py:170-203` — `select_comparison` is complete
  and tested (`tests/test_compare_picker.py`): given the pool's openings, companies,
  assertions and existing comparisons, it returns one `ComparisonSuggestion(target,
  opening_a_id, opening_b_id)` — the single best next question, or `None`. No route calls
  it yet.
- **F2** — `src/screen/api/scoring.py:47-74` — `pool_for_screening` already accepts
  `comparisons_by_target`/`companies_by_opening` and threads them into
  `dimension_posteriors`, but grep across `src/` (excluding tests) shows zero callers pass
  either — `src/screen/api/routes.py` and `src/screen/web/routes.py` both call
  `pool_for_screening` with only the first three positional args. The comparison-fitted
  covariance the parent bearing's north-star criterion depends on is inert in production
  today.
- **F3** — `src/screen/store/repo.py:188-209` — `append_comparison` and
  `comparisons_for_target` exist and are tested; nothing in `src/screen/web/` or
  `src/screen/api/` calls either.
- **F4** — `src/screen/types.py:221-236` — `Comparison` (the stored/logged Pydantic model,
  distinct from `screen.score.compare.Comparison`, the pure-fit dataclass) already carries
  `predicted_a_beats_b` and `outcome: ComparisonOutcome` — the calibration-log record
  compare-scouting G6 named is a completed field, needs only a route to write it via
  `screen.score.compare_probability.pre_comparison_probability`.
- **F5** — `src/screen/web/routes.py:178-225` — `_dimension_groups` groups one opening's
  assertions by rubric target and attaches a cached digest per group; compare-scouting G7
  already flagged this needs factoring for two-opening reuse — confirmed still true, no
  refactor has happened (`_dimension_groups` still takes one `opening_id`).
  `digest_for_target` (`src/screen/digest/service.py:39-60`) is the reusable primitive
  underneath it and takes one `opening_id` too — calling it twice, once per side, is the
  straightforward shape, not a rewrite.
- **F6** — `src/screen/web/routes.py:1-6` module docstring — the established pattern is
  server-rendered HTML + HTMX partial swap, JSON routes stay read-only; a comparison
  screen is a `web/routes.py` addition, not an `api/routes.py` one (no prior compare JSON
  endpoint exists or is implied).
- **F7** — `src/screen/web/templates/_rating_content.html:1-42` — one opening's dimension
  list, with a `fit-control` HTMX form per assertion. A comparison screen showing two
  openings side by side on one target is new template surface, not a variant of this
  partial (this renders every dimension; a comparison screen renders one target at a
  time, per F1's suggestion shape).
- **F8** — `src/screen/web/routes.py:277-289` (`index`) — the queue page is the natural
  place to route the operator into a comparison (a link/button, HTMX-driven per the
  existing `/batch` pattern at line 436), consistent with domain-model's Workflow: routing
  surfaces what needs the operator's judgment.
- **F9** — decisions.md W5 — precedent retrieves and shows, never decides; the comparison
  screen is an operator action (A/B/tie), not a precedent display, so W5 doesn't
  constrain it directly, but it's a resonant precedent for "predicted_a_beats_b shown or
  logged silently" (→ compare-scouting G6 already chose logged silently, calibration-only).
- **F10** — compare.md §Not Doing — explicitly scoped this out: "The comparison screen,
  its route, and end-to-end web tests — a later bearing." This scouting report is that
  later bearing's terrain.
- **F11** — `src/screen/score/compare.py:33-36` — `COMPANY_LEVEL_TARGETS` (mission,
  trajectory, peer, agentic, domain) auto-tie same-company openings; `select_comparison`
  already excludes same-company pairs on those targets (compare_picker.py:155-159), so
  the screen never needs to special-case "these two openings share a company" — the
  picker guarantees it won't suggest that pair on those targets.
- **F12** — `tests/test_web.py` — no comparison-related test exists yet; the existing
  rating-page test suite (`test_rate_opening_*`) is the closest analog for what an
  end-to-end comparison-screen test would look like (client fixture, db_path fixture,
  HTMX partial assertions).
- **F13** [!] — the picker (F1) returns one best suggestion; the screen's flow (does the
  operator see a queue of upcoming suggestions, or one at a time with "next" advancing
  after each judgment?) isn't decided by anything scouted — ride as a Recalibrate When or
  settle in Agreed if the operator has a preference.
- **F14** [!] — nothing scouted says where in navigation the comparison screen lives:
  a dedicated `/compare` route reached from the queue (F8), a link per opening pair, or
  folded into the rating page. Existing prior art (F8) leans toward `/compare` as its own
  page, but this is a real open UX choice, not a finding.

- **F15** — operator — this node's tracer bullet is manual selection: pick any two
  openings and a dimension, declare a winner or tie, confirm it moves the live ranking.
  `select_comparison` (F1) choosing the pair/dimension for the operator is deferred to a
  later node — this node doesn't need it at all.

## Explore Further

- `tests/test_compare_picker.py`, `tests/test_pool_comparisons.py` — full behavioral spec
  of everything the screen wires together.
- `src/screen/web/templates/_boundary_glyph.html` — the macro pattern to follow if the
  comparison screen wants any visual glyph (none scouted as needed yet).
