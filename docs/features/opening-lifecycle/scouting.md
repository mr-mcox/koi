---
feature: opening-lifecycle
type: scouting
date: 2026-09-09
commit: 93dd9c2
---

## What We're Doing

Operator has applied to some openings and had conversations/rejections with others.
Wants to filter these out of the ranked queue without deleting them — rulings and job
descriptions stay useful for the calibration corpus and future first-pass screening.
Four states, no ranking behavior for any non-`screening` state right now. A job coach
told the operator 85% of offers come from human interaction, so "easy apply"/cover-letter
tooling isn't where effort goes — the state that matters most day-to-day is a marker that
an opportunity is being pursued outside koi (unconventional outreach: warm intros, or
finding someone who wrote a blog post and might be reachable), without needing to be
granular about what that pursuit consists of.

## Findings

- **F1** — domain-model.md, Opening section — Opening already carries a `Pipeline stage`
  field in the design: `screening → handed-off → applied → closed(outcome)`, described as
  "deliberately thin; other systems do real application tracking. The holding area is a
  view over this field." Never implemented.
- **F2** — `src/screen/types.py:24-32` — `Opening` (frozen, `extra="forbid"`) has no stage
  field today: `id, company_id, title, url, research_trace_id, research_turns_budget,
  created_at`. This is a net-new field, not a rename.
- **F3** — `src/screen/store/migrations/0001_create_domain_tables.sql` — `openings` table
  columns match F2 exactly; a stage column needs a migration (pattern: `0006_add_research_
  turns_budget.sql`, `0007_add_dimension_ruling_covered_assertion_ids.sql` — additive,
  numbered, one column each).
- **F4** — `src/screen/store/repo.py:43-59` — `upsert_opening` is a single INSERT...ON
  CONFLICT DO UPDATE that overwrites every column from the `Opening` object each time it's
  called (e.g. on re-identification). A stage field stored directly on `Opening` would be
  clobbered by any future upsert that doesn't carry it forward — same risk profile as
  `research_turns_budget` already has today, not new, but worth the same care.
- **F5** — `src/screen/web/routes.py:_scored_openings` (`~L217`) and `list_openings`
  (`repo.py:124`) — the queue's candidate set is *every* row in `openings`, unfiltered.
  Anything with a non-`screening` stage needs to be excluded here (or in `list_openings`)
  to leave the ranked queue.
- **F6** — `src/screen/web/routes.py:_queue_items`/`queue.html` — the queue view has no
  concept of "closed/applied" today; there's no existing filter param or toggle to extend.
- **F7** — operator — exactly four states, agreed: `screening` (in queue, ranked),
  `pursuing` (working an unconventional in — warm intro search, blog-author outreach —
  not yet applied, not yet decided to apply), `applied` (submitted, waiting), `closed`
  (rejected/withdrawn/ghosted — an outcome, terminal). No ranking or sub-state modeling
  for `pursuing`/`applied`/`closed`; the sole job of these three is "out of the live
  queue, still retrievable."
- **F8** — operator — retrieval requirement ("pull up an opportunity, recall what I
  thought of it") is satisfied by existing Ruling/Assertion history once an opening is
  filtered out of the live queue — no new note/summary field needed, just a way to reach
  a de-queued opening's existing rating view.
- **F9** [x] — operator: no outcome sub-typing needed — superseded/merged into F18.
- **F10** [x] — is outreach automation (finding blog-post authors, second-degree
  connections) in scope for this feature? Operator: **out of scope** — a separate, later
  feature. This feature only needs to leave room for a future consumer of the `pursuing`
  state; it does not build any outreach tooling. → bearing §Not Doing.
- **F11** — operator — obtainability (already a collected non-scoring target, W1 in
  decisions.md) is the domain concept behind `pursuing`'s two current strategies: second-
  degree connections for an intro, or a blog post (not necessarily company-authored) whose
  author might be reachable — knowing merely that a named person works there is itself
  useful, independent of any blog post. This is background for the eventual outreach
  feature, not something this feature stores structurally.
- **F12** — decisions.md W1 — obtainability is explicitly "collected, not modeled," a
  non-scoring assertion target, structurally excluded from standing (wall 3). Lifecycle
  stage must not touch scoring in the same way — it's a orthogonal, non-scoring axis,
  same wall.
- **F13** — `src/screen/web/routes.py:index` / `queue.html:1-27` — the only page listing
  openings; no per-opening "mark applied/pursuing/closed" affordance exists in the rating
  view (`rating.html`) either — an HTMX form + POST route (same shape as `submit_ruling`,
  `submit_dimension_ruling`) is the established pattern for a state-changing action from
  that page.
- **F14** — `src/screen/api/routes.py` — `/queue` JSON endpoint also calls `list_openings`
  unfiltered; if `list_openings` filters by stage, this endpoint's behavior changes too
  (no separate fix needed, same finding as F5).
- **F15** [x] — no existing page shows *all* openings including non-`screening` ones.
  Operator: wants a real filter-by-stage view, not just a bookmark — retrieval is a named
  workflow. → bearing §Done When / §Approach (archive/filter view).
- **F16** — operator — when an opening leaves `screening` (e.g. heard back from a company,
  moved to `applied`/`closed`), it must stop being one of the `top_k` openings that sets
  the bandit/queue boundary — a de-queued opening should not still anchor "what's the
  bar for the top 5."
- **F17** — `src/screen/web/routes.py:_scored_openings` (`~L217`), `_kth_result` (`~L248`),
  and `src/screen/research/batch.py:287` all derive their candidate set from
  `repo.list_openings`. Filtering `list_openings` (or adding a filtered variant used by all
  three) to `screening`-stage openings only therefore satisfies F5, F14, and F16 with one
  change — the bandit boundary, the ranked queue, and the JSON `/queue` endpoint all read
  through this same function and need no separate fix.
- **F18** — operator — no outcome sub-typing for `closed` (F9 resolved): a single terminal
  `closed` stage, no `outcome` field. "If I need to distinguish why it's closed, we can
  build that. If I land a job, this whole project is done."
