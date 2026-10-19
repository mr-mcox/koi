---
feature: queue-staleness
type: scouting
date: 2026-10-19
status: orienting
scouting_for: ./bearing.md
---

## Findings

- **F-QS1 · The compare flow already does background work while the operator is thinking** — `GET /compare` can start `run_prescreen_in_background` through `request.app.state.compare_progress`, and `/compare-status` polls that state until the pass finishes (`src/screen/web/routes.py:481-509`, `src/screen/web/routes.py:635-645`). The code already treats compare as a “do work in the background, show me the next thing when ready” interaction.
- **F-QS2 · The next compare is decided after the write, not before it** — `POST /compare` appends the operator judgment to SQLite and immediately redirects back to `/compare`; the next suggestion is recomputed on the redirected GET, not reused from the POST response (`src/screen/web/routes.py:573-632`). Any reuse would have to live above the DB write path.
- **F-QS3 · Background compare work already advances through multiple easy pairs** — `run_prescreen` re-reads the live screening pool on each iteration, computes a fresh suggestion, persists any confident Jev ruling, and keeps looping until it hits the first uncertain suggestion or a safety cap (`src/screen/api/pool.py:256-312`). So the system already knows how to keep moving the compare state forward in small committed steps.
- **F-QS4 · There is no compare-state cache keyed to the pool version today** — `CompareProgress` only tracks `running`, `completed`, `ruled`, `final_suggestion`, and `final_suggestion_jev_read` (`src/screen/api/pool.py:235-253`). Nothing in the current flow records which pool state produced a suggestion, so stale-by-one behavior would be new state, not a reuse of existing state.
- **F-QS5 · The scoring model is pool-scoped, so stale suggestions are older hints against the same joint posterior** — the architecture says the pool is scored jointly and that comparisons change the pool-wide posterior seam (`docs/architecture/domain-model.md:115-124`, `docs/architecture/decisions.md:266-271`). That supports treating a one-step-stale suggestion as a plausible hint, but also means freshness has to be explicit rather than assumed.
