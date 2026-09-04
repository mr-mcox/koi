---
feature: research-batch-web-trigger
type: scouting
date: 2026-09-04
commit: eb492bb
---

## What We're Doing

`docs/CURRENT.md`'s framing: `research-batch` and `bump-research-turns-budget` are
CLI-only today. Now that the batch actually reasons about which opening to spend on
(research-pass-bandit, `status: done`), triggering a batch and setting its turn budget
from the web UI — rather than a terminal — is the obvious next surface. No scouting
existed for it before this session; the research-pass-bandit bearing named it and
deferred it explicitly.

## Findings

- **F1** — `research-pass-bandit/scouting.md` F27 (operator, closed) — "wants a UI
  affordance to kick off a research batch and set its turn budget from the web UI, not
  just the CLI. Explicitly fine deferring this to a future bearing if this one is already
  heavy." `research-pass-bandit/bearing.md` §Not Doing confirms: "A web UI affordance to
  trigger a research batch and set its turn budget, and removing
  `bump-research-turns-budget`/`research-batch` as CLI commands once that affordance
  exists — explicitly deferred to a separate future bearing, not built here."
- **F2** — `research-pass-bandit/scouting.md` F28 (operator) — once a UI affordance
  exists, `bump-research-turns-budget` (`src/screen/intake/cli.py:224-237`) and
  `research-batch` (`cli.py:336-380`) are named as "temporary CLI" the operator expects
  to retire. `backfill-research-turns-budget` (`cli.py:179-192`) is a one-time migration
  helper, not implicated — explicitly not named for retirement.
- **F3** — `src/screen/intake/cli.py:336-380` (`research_batch`) — the CLI command's
  entire body is the one function to reuse: seeds an `np.random.default_rng(config.seed)`,
  loops up to `batch_size` times, each iteration calling `_eligible_weights` (`cli.py:
  321-333`), `draw_opening` (`bandit.py:39`), `_resume_opening` (`cli.py:240-276`, one
  network-calling research turn), and echoing a trace line. Nothing here is CLI-specific
  except the `click.echo` calls and the `click.argument` decorator — the loop body is a
  plain function of `(data_root, conn, batch_size)` already.
- **F4** — `src/screen/intake/cli.py:226-237` (`bump_research_turns_budget`) — trivial:
  `get_opening` → `model_copy(update={"research_turns_budget": new_budget})` →
  `upsert_opening`. No batch, no loop, no network call — this one is safe to duplicate as
  a fast synchronous POST route.
- **F5** — `src/screen/intake/cli.py:240-276` (`_resume_opening`) — each turn calls
  `dispatch()` (`research/dispatcher.py:90`), which is synchronous and makes real
  BAML/Tavily network calls (no `async def` anywhere in `dispatcher.py`,
  `baml_planner.py`, or `browser.py`). `docs/architecture/learnings.md` Q3: one full pass
  measured at 215 seconds, 12 searches, ~$1.10 — that's the ceiling for one *pass*; one
  *turn* (one action) is a fraction of that, but a `batch_size`-turn batch run is
  `O(batch_size)` sequential network round-trips, easily tens of seconds to minutes.
- **F6** ⚠ — `src/screen/api/app.py:56` / `src/screen/web/routes.py` — every existing web
  route (`index`, `rate_opening`, `submit_ruling`, etc.) is `def`, not `async def`, and
  FastAPI runs sync route handlers in a threadpool — a request completes only when the
  handler returns. There is no existing async/background-task/polling precedent anywhere
  in `src/screen/web/` or `src/screen/api/` (`grep -rn "BackgroundTasks\|async def" src/screen tests` returns
  nothing outside FastAPI/Starlette internals). Wiring `research_batch`'s loop directly
  into a synchronous POST handler would hold that request open for the batch's full
  duration — one worker process (`./run serve` execs a single `uvicorn` process, no
  `--workers` flag, `run:19`) blocked on network I/O for potentially minutes, with no
  other route servable meanwhile (uvicorn's default single worker, default sync-threadpool
  concurrency notwithstanding — one long request still monopolizes the connection the
  operator is watching, and `TestClient`-style test infra has no support for polling an
  in-flight batch).
- **F7** — `.venv/lib/python3.14/site-packages/starlette/background.py` — FastAPI ships
  `BackgroundTasks` (`fastapi.BackgroundTasks`, already a transitive dependency, no new
  package): `response = ...; background_tasks.add_task(fn, *args); return response`. The
  task runs after the response is sent, via `run_in_threadpool` for a sync function — no
  new dependency, no asyncio rewrite of `dispatch()`/`_resume_opening()` needed.
- **F8** — `src/screen/web/templates/_rating_content.html:14-15,43-44` (HTMX pattern
  already used for `submit_ruling`/`submit_dimension_ruling`) — every existing mutating
  route swaps a partial back via `hx-post` + `hx-target` + `hx-swap="outerHTML"`. There is
  no polling (`hx-trigger="every ..."`) or SSE precedent anywhere in the templates
  (`grep -n "every\|sse" src/screen/web/templates/*.html` — none). A "batch running" status
  surface serving the operator during a multi-minute batch would be new UI vocabulary, not
  a reuse of the existing submit-and-swap shape.
- **F9** — `src/screen/api/deps.py:16-23` (`get_db`) — one SQLite connection per request,
  opened and closed within that request's lifetime. A `BackgroundTasks` callback that
  outlives the request cannot reuse the request's `Conn` dependency — it needs its own
  `database.connect()` call, mirroring how `_resume_opening`/`research_batch` already open
  their own connection via `connect(_db_path_for(data_root))` rather than a FastAPI
  dependency.
- **F10** — `src/screen/api/app.py:47,57` (`Database`, `app.state.database`) — the route
  layer already has a `Database.connect()` factory reachable via `request.app.state
  .database` — a background task closure can capture this same `Database` instance
  (passed at scheduling time, not re-derived) rather than re-deriving `data_dir()` fresh,
  matching how `app.state.digester` is threaded into web routes today (`routes.py:538`,
  `_rating_context_for_request`).
- **F11** — `scoring.yaml:78` (`research_turns_budget: 5`) — the batch's *count* dial
  (`batch_size`, the CLI's positional arg) and the *per-opening cap* dial
  (`research_turns_budget`) are two different numbers already conflated in naming
  (`bump-research-turns-budget` sets the per-opening cap; `research-batch N`'s `N` is the
  cross-opening spend count). A web form triggering a batch needs to expose `batch_size`
  specifically — the per-opening `research_turns_budget` bump (F4) is a separate, second
  affordance the operator asked for in the same breath (F1's "and set its turn budget"
  reads ambiguously between the two; operator confirmation needed, see open thread below).
- **F12** — `src/screen/web/routes.py:333-337` (`index`) — the queue page is the only
  page rendering "all openings" today; no per-opening "kick off research" button exists,
  and no page-level "run a batch across the backlog" button exists either. Either
  affordance is new template markup on `queue.html`, not a wire-up of a half-built control.
- **F13** — `tests/test_web.py` (`TestClient` against `create_app`) — existing web tests
  seed data directly via `screen.store.repo` and hit routes synchronously; a batch-trigger
  test needs either a fake planner/browser injected into the app (no such injection point
  exists today — `create_app(db_path, digester)` only accepts a digester override,
  `app.py:42`) or must assert on `BackgroundTasks` scheduling/DB side effects without
  waiting out a real multi-minute run.
- **F14** [ ] — does "set its turn budget" (F1) mean the batch's `batch_size` (how many
  turns to spend this run), the per-opening `research_turns_budget` cap (F4's existing
  bump), or both exposed as separate controls? The CLI has both as separate commands
  today; the web UI could offer one, the other, or both — this changes what the bearing's
  Approach commits to and needs the operator's read before drafting Done When.
- **F15** [ ] — should the queue page (F12, all-openings view) host the batch trigger, a
  new dedicated page, or both a per-opening "research this one" and a page-level "run N
  turns across the backlog" control? `research-batch`'s candidate set is cross-opening
  (F3); `bump-research-turns-budget` is per-opening (F4) — these may want different homes.
- **F16** [ ] — while a batch runs in the background (F6/F7), what does the operator see?
  Options observed in the codebase's existing vocabulary: nothing until they reload the
  queue (cheapest, no new UI), a static "batch running" banner with no live update (cheap,
  one new template partial), or a polling/HTMX-`every` status strip (new interaction
  pattern, F8 — no precedent to reuse). This is a UX call, not a mechanical one — the
  bearing needs a stated default with room to be overridden.
- **F17** [ ] — should the same request also let the operator kick off a *single-opening*
  resume (the CLI's plain `research <opening-id> <turns>` command,
  `cli.py:279-298`), or is only the cross-opening `research-batch` in scope? Neither F1 nor
  F2 mentions `research` (singular) for retirement or replacement — only `research-batch`
  and `bump-research-turns-budget` are named. Treating `research` (singular) as
  out-of-scope by default, but this is a scope-boundary call worth the operator's explicit
  sign-off given how closely related the three commands are.
