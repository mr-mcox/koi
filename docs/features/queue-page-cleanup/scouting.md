---
feature: queue-page-cleanup
type: scouting
date: 2026-08-26
commit: df40101557c67554f0f11122b5a943e186e0a490
---

## What We're Doing

Queue page UI cleanup, four things that bug the operator:
1. "No batch running" is noise when idle; when a batch *is* running, what's wanted is an
   ETA, not a play-by-play of which opening it's on.
2. Research turns should default to 50 with a single button to start — no separate
   number-entry ritual.
3. Research turns / start contested review / archive read as three unrelated actions each
   on their own line; they should feel like one family, styled like the rest of the page.
4. The `turns_used/turns_budget` counters (e.g. "5/5", "6/5") on each queue row are noise.
   The operator suspects the whole `research_turns_budget` mechanism is a vestigial idea —
   the multi-armed bandit doesn't use it as a "healing" refill target in practice — and it
   might be rippable out of the DB. **Operator has split this off**: this bearing covers
   only "don't show those values on the queue row"; the schema/mechanism-level question is
   a separate line of work.

## Findings

- **F1** — `src/screen/web/templates/queue.html:6-16` — current queue page structure: a
  `#batch-status` div (status line), a `<form class="batch-start">` with a number input
  (default 5) + "Start batch" button, then two bare `<p><a>` lines for "Start contested
  review" and "Archive".
- **F2** — `src/screen/web/templates/_batch_status.html` — when idle, renders
  `<p class="batch-idle">No batch running.</p>`; when running, renders spent/total turns
  and (optionally) `current_opening_id`; polls `/batch-status` every 2s via htmx while
  running.
- **F3** — `src/screen/web/routes.py:755-799` — `POST /batch` takes `batch_size` (form
  field, `gt=0`, no default value server-side — the `value="5"` lives only in the HTML
  input). `GET /batch-status` is the htmx poll target, returns the same partial.
- **F4** — `src/screen/research/batch.py:319-329` — `BatchProgress`/the progress dict
  (`total`, `spent`, `current_opening_id`, `touched`, `running`) carries no timestamp
  anywhere. No `started_at`, no per-turn timing recorded in-process.
- **F5** — `src/screen/research/batch.py` (whole file, grepped) — no wall-clock timing is
  captured anywhere in the batch/dispatch path (`time.time`/`perf_counter`/`elapsed` all
  absent); only `datetime.now(UTC)` timestamps written into research-trace *event* records
  on disk (`dispatcher.py`, `batch.py:200`), not read back for rate estimation.
- **F6** — no finding: an ETA computed from *no timing data at all* would be invented, not
  measured — in tension with the house epistemology's "measure before model" (AGENTS.md).
- **F6b** [x] — operator: wants real per-turn timing recorded, then an ETA estimated from
  it — lightweight, no new dependency → §Approach. tqdm's own algorithm (web search,
  tqdm docs "Exponential moving average smoothing factor for speed estimates... default
  0.3"): keep an EMA of seconds-per-turn (`rate = smoothing*current + (1-smoothing)*prior`,
  smoothing=0.3 is tqdm's default), `eta_seconds = remaining_turns * rate`. This is plain
  arithmetic on a timestamp diff, not a library — pulling in tqdm itself would import its
  progress-bar rendering machinery for a UI we're not using.
- **F7** — `tests/test_web.py:1758-1808` — three tests assert on the literal strings
  "Batch running" and "No batch running" in response text: `test_batch_start_returns_before_
  turn_is_spent`, `test_second_batch_start_is_rejected_while_one_is_running`, and the
  polling loop that waits for "No batch running" to reappear after completion.
- **F8** — `src/screen/web/routes.py:266-296` (`_queue_items`) — builds the queue row dicts;
  `turns_used`/`turns_budget` come from `opening_research_status(data_root, opening)`
  (`src/screen/research/batch.py:516-521`), which replays the research trace file and reads
  `opening.research_turns_budget` off the `Opening` row. `queue.html:25` renders
  `{{ item.turns_used }}/{{ item.turns_budget }}` as `<span class="research-status">`.
  No test in `test_web.py` asserts on this span's text/class (grepped `research-status`,
  `turns_used`, `turns_budget` in `tests/test_web.py`: no hits) — safe to drop the display
  without touching a named test.
- **F9** — `src/screen/web/routes.py:9-16` (form) — batch-size input has no `max`, only
  `min="1"`; operator wants a hardcoded default of 50, single button, no separate number
  field to fill in first.
- **F10** — `src/screen/web/static/app.css` — no shared button/action-row style exists yet
  (grepped `<button>`/`.btn`: only bare `<button type="submit">` in `queue.html`,
  `rating.html`'s noscript fallback, and `_rating_content.html`'s fit-segment buttons,
  which are a different, purpose-built control). `.archive-link`, `.stage-select`, and
  `.archive-filter` (`app.css:390-403,468-471`) are the closest existing "understated pill
  link" patterns already used elsewhere on the page (stage selector, archive filter chips).
- **F11** — decisions.md/domain-model.md (architecture index read) — nothing in the girder
  list or volatile list covers the queue page's HTML/CSS or the batch-status polling
  mechanism; this is open space per the architecture index.
- **F12** — `src/screen/types.py:39`, `scoring.yaml` (`research_turns_budget: 5`) —
  `research_turns_budget` is a per-`Opening` DB column, seeded at intake and backfillable
  via `screen backfill-research-turns-budget` CLI (`intake/cli.py:174-186`). Confirms F8's
  premise that this is stored state, not derived — but changing/removing the column is
  explicitly out of scope per the operator's split.
