---
feature: queue-page-cleanup
type: bearing
date: 2026-08-26
commit: df40101557c67554f0f11122b5a943e186e0a490
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

The queue page's batch controls and nav links read as three unrelated widgets bolted onto
the page, the idle-state message is noise, and per-row research-turn counters add nothing
the operator uses. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] Idle queue page shows no "no batch running" message; a running batch shows an ETA,
      not a live opening id → manual check + `tests/test_web.py` batch tests updated to
      match new copy
- [ ] The batch-start form has no visible number input; submitting starts a 50-turn batch
      → `tests/test_web.py::test_batch_start_form_validates_batch_size` and friends still
      pass against the new form
- [ ] Research-turns start, "start contested review", and "archive" render as one visually
      cohesive action row using the page's existing pill-link styling → manual check
- [ ] Queue rows no longer show `turns_used/turns_budget` → grep `research-status` absent
      from `queue.html`
- [ ] `run_batch`/`BatchEngine` record wall-clock time per turn and expose an EMA-based ETA
      in the progress dict → new unit test on the ETA calculation

## Approach

- Track per-turn elapsed seconds in `BatchProgress`/the progress dict (a new `started_at`
  timestamp set once, plus rate updated after each turn) and compute ETA as an exponential
  moving average of seconds-per-turn (smoothing=0.3, tqdm's default), `eta = remaining *
  rate` — plain arithmetic, no new dependency (→ scouting F6b).
- Batch start form becomes a single submit button with `batch_size` hardcoded server-side
  default of 50 (still a `POST /batch` form field, just no visible input) (→ scouting F9).
- Reuse the existing pill-link visual language (`.archive-link`/`.archive-filter` family,
  scouting F10) for a new shared action-row style rather than inventing a button system —
  cheapest way to make three actions read as kin.
- Drop `turns_used`/`turns_budget` from `_queue_items` and `queue.html` display only; the
  `Opening.research_turns_budget` column, `opening_research_status`, and the CLI backfill
  command are untouched (→ scouting F12, explicitly split off).

## Not Doing

- Anything to `research_turns_budget` storage, the bandit's use of it, or the DB schema —
  split off as separate work (→ scouting "What We're Doing" item 4).
- A real progress bar / tqdm dependency — ETA display only, no bar widget (→ scouting F6b).

## Testing

Test-first by default. Exempt:
- `src/screen/web/static/app.css` — visual/styling changes, no behavior to assert

## Recalibrate When

- If ETA swings wildly turn-to-turn (e.g. first turn taking far longer/shorter than
  steady-state), reconsider the smoothing constant or warm-up handling before shipping.
- If the "single button, 50 turns" default turns out to need an override some days, stop
  and ask before adding back a hidden/advanced input.

## Agreed

- ETA is estimated from newly-recorded real per-turn timing (EMA, tqdm-style), not
  invented from nothing — operator confirmed measure-first over drop-it (→ scouting F6b)
