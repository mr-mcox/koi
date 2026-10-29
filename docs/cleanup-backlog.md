# Cleanup backlog

Outstanding structural cleanups from the October 2026 codebase survey. Each item is
scoped to one PR or commit and written so a fresh session can pick it up from this file alone.

**Working an item:** read AGENTS.md first. Pass `uv run python scripts/check.py` with no
`.env` values set (the suite is hermetic, so it must pass without them). When the PR
or commit lands, mark the item done here with a link to it. Add items in the same shape. Remove an
item only once it is done or explicitly dropped, and say why.

**Parallel work:** each item lists the files it touches. Items whose lists are disjoint can
run in separate worktrees at the same time. Each wave below can run in parallel; finish a
wave before starting the next, because later waves move files the earlier ones edit.

| Wave | Items | Notes |
|---|---|---|
| 1 | A, B, C, D | B and D both make small edits to `wiring.py`; whichever merges second rebases |
| 2 | E, then F and G | F and G both touch `web/routes.py` imports of `api/pool.py`, so serialize them or agree on module names first |
| 3 | H | Moves every test file; run it alone |
| 4 | I, J | Touch nearly every file; run each alone |
| any | K | Operator decision, not code |
| any, after A | L | A correctness fix, not a cleanup; shares `scripts/backtest_jev_routing.py` with A |
| after G | M | Adds tests to files F, G and H move; run it between G and H, or after H, but not alongside them |
| after M | N | Touches `browser.py` and `tests/test_browser.py`, which M edits |
| after M | O | Touches files across `src/`; run it alone |
| after M | P | Touches only `compare/prescreen.py` and its tests |

---

## A. Delete dead code and fix stale references — *done* at commit 4b39eb7f08d71e25ec09a61658b143b4c59d2c37

Code that nothing in production reaches, kept alive only by its tests:
- `ResearchTraceLockedError` (`intake/research_trace_io.py`) is never raised. Delete it
  and its `issubclass` test in `tests/test_research_trace.py`.
- `PoolScore.unguarded_trace` (`score/types.py`) is written by `score/scorer.py` and never read.
- `_prior_variance` (`score/compare_picker.py`) is called only from tests. Delete it
  with its tests.
- `get_dimension_digest_by_id` (`store/repo.py`) is also called only from tests, but
  keep it: it is the unwired half of the recalibration audit path, and item L calls it.
- `scripts/check.py` lists `src/screen/embed/fastembed_embedder.py`, which doesn't exist,
  in `OMIT_FROM_COVERAGE`. Have `check.py` read the omit list from `pyproject.toml`
  instead of duplicating it.
- `scripts/backtest_jev_routing.py` calls `JevVerdictProvider(TypeSafeClient())`, but the
  constructor takes `(config, client)`, so the script is broken. Fix it or delete it (ask
  the operator whether they still use it).

Stale text:
- `score/compare_picker.py`: the module docstring gives the formula as
  `closeness_overall × …`, but `_best_pair` says the closeness multiplier was removed. The
  docstring cites `picker-variance-share.md`, which isn't in the repo, and lines 267–292
  explain the closeness gate twice (once in the docstring, once inline).
- `research/__init__.py` and `docs/architecture/README.md` state contradictory import
  rules for intake and research (item E settles this; here, just make them agree with
  what E will enforce).

Touches: `intake/research_trace_io.py`, `score/types.py`, `score/scorer.py`,
`score/compare_picker.py`, `store/repo.py`, `scripts/check.py`,
`scripts/backtest_jev_routing.py`, their tests.

## B. Remove the CLI — *done* at commit 6b4c200

The operator only uses `./run` to serve the app. `backfill-jev-classification` was a
one-time migration. `backfill-digests` only fills missing digests (it never forces a
refresh), and dispatch already warms digests after every pass.

Delete:
- `src/screen/intake/cli.py`, `src/screen/__main__.py`, `tests/cli/`
- `CliDeps` and `build_cli_deps` (`wiring.py`), their test in `tests/test_wiring.py`, and
  the `fake_cli_deps` helper
- the backfill subcommands in `./run`, and `python -m screen` in AGENTS.md and README
- `repo.update_assertion_classification` and `repo.delete_assertion`. These are the two
  "scoped exceptions to Wall 6" (decisions.md E6); with them gone, assertions are
  append-only with no exceptions. Record that in decisions.md.
- `digest_for_target(force=…)`, if nothing else passes `force`.
- the `__main__.py` entry in both coverage omit lists.

Touches: `intake/cli.py`, `__main__.py`, `wiring.py`, `store/repo.py`, `digest/service.py`,
`run`, `pyproject.toml`, `scripts/check.py`, `tests/cli/`, `tests/helpers.py`,
`tests/test_wiring.py`, AGENTS.md, README.md, `docs/architecture/decisions.md`.

## C. Drop obtainability and the non-scoring target concept — *done* in cc980c3

`non_scoring:obtainability` is the only non-scoring target and hasn't proven useful. The
scorer already ignores it (it only iterates `dimension_weights`), but the research
planner spends turns on it and the extractor spends tokens on it.

- Remove the `non_scoring` section from `rubric.yaml`; remove `_NON_SCORING_TARGETS` and
  its entry in the `Target` Literal (`types.py`).
- Remove the non-scoring branches in `extract/prompt.py` (render, the `for_dimension`
  fallback, the placeholder anchors in `fit_anchors_for_dimension`) and
  `all_non_scoring_slugs`, including its use in `research/batch.py`.
- Remove the "Non-scoring slug" lines from `baml_src/extract.baml` and
  `baml_src/research.baml`, then regenerate `baml_client` with `baml-cli generate`. Never
  edit `baml_client` by hand.
- The live DB is safe: the `store/mappers.py` read path drops rows whose target has left
  the vocabulary, with a warning.
- Wall 3 ("non-scoring targets never enter rank") then guards nothing. Append a
  decisions.md entry that retires it, with the reason; update the walls list in
  `domain-model.md` and the web-route docstring in `web/routes.py`.

Touches: `rubric.yaml`, `types.py`, `extract/prompt.py`, `research/batch.py`, `baml_src/`,
`baml_client/`, `web/routes.py`, `tests/test_extract_prompt.py`, `tests/test_rubric.py`,
`tests/test_types.py`, `docs/architecture/`.

## D. Put both research turn budgets in `scoring.yaml` — *done* in 70140c8

Intake runs a fixed number of research turns, and every later batch pass runs a fixed
block. The two numbers live in different places:
- Intake: `INTAKE_FIRST_PASS_TURN_BUDGET = 5` in `research/batch.py`, overridable by the
  `SCREEN_TURN_BUDGET` env var (read in `wiring.py`), and threaded through `intake_url`
  and `identify_research_trace` as `turn_budget`.
- Later passes: `min(research_target_action_cap, remaining batch)`, with the cap set to 3
  in `scoring.yaml`.

Change: add `intake_turn_budget` to `scoring.yaml`, then remove the constant, the env
override and the `turn_budget` parameters.

**Operator decision first:** `research_target_action_cap` is both the batch block size
and the planner's per-target action cap (`LoopState.active_target_action_cap`). Either
split it into two keys, or keep one number and rename it (e.g. `research_block_turns`).

Touches: `scoring.yaml`, `score/loader.py`, `score/types.py`, `research/batch.py`,
`intake/pipeline.py`, `wiring.py`, `tests/intake/`, `tests/test_research_batch.py`.

## E. Break the intake↔research import cycle and enforce dependency direction — *done* in 0e93aee

The research trace now lives in `screen/research_trace/` (`events.py`, `trace_io.py`,
`replay.py`, `ids.py`), which both intake and research import; `trace_io.py` also holds
`research_trace_path_for`, `read_page_content`, `record_event` and
`ResearchTraceMissingError`, moved out of `research/batch.py`.

`api/scoring.py` and `rank_screening_pool`/`screening_pool_inputs` moved to
`screen/pool.py`, below `api/` and `web/`, so `research/batch.py` ranks the pool without
importing the web layer. `api/pool.py` is now only the prescreen engine — F folds it into
`screen/compare/` and may move `screen/pool.py` with it.

`tests/test_import_direction.py` parses imports with `ast` and asserts the layering
(every top-level module must be placed in a layer; imports never point up; `research/`
never imports `intake/`). `screen/api/main.py` is the one declared exception, as the ASGI
entrypoint that calls the composition root. The README girder line no longer says
*unenforced*.

Two branches that the move left under the per-file coverage gate got tests rather than
exemptions: `resume_opening` with no remaining budget, and the speculative prescreen's
iteration bound (which gained a `max_iterations` parameter mirroring `run_prescreen`'s).

## F. Split pairwise comparison out of `score/` and the prescreen engine out of `api/` — *done* at 9d6d35e

`screen/compare/` holds the comparison workflow: `picker.py` (was
`score/compare_picker.py`), `probability.py` (was `score/compare_probability.py`),
`rubric_gate.py` (was `score/rubric_gate.py`) and `prescreen.py` (was `api/pool.py`).
`api/` is now HTTP only (`app`, `deps`, `routes`, `main`).

The pairwise fit (`score/compare.py`) stayed in `score/`, renamed `score/pairwise.py`.
`screen/pool.py` consumes it to rank the pool, and the prescreen engine reads that
ranked pool, so moving the fit into `compare/` would have made `compare` and `pool`
import each other. Moving `pool.py` into `compare/` instead would have filed pool
ranking, which research uses too, under comparison. `tests/test_import_direction.py`
places `compare` in the layer above `pool`, so the pool ranking can't import it.

## G. Split `web/routes.py` by feature and type the app's mutable state — *done* in [#2](https://github.com/mr-mcox/koi/pull/2)

`web/routes.py` now only aggregates one router per feature: `queue.py` (queue, rating,
assertion rulings, prune-stale), `compare.py`, `archive.py` (stage changes and the
archive), `batch.py` and `intake_queue.py`. What more than one of them renders with
(templates, `BoundaryGlyph`, accent hues, `dimension_groups`, static files) is in
`web/common.py`.

The compare decisions live in `compare/session.py`: `CompareSession` bundles the
prescreen's state, cache, progress and in-flight speculation, alongside the cache
legality and staleness rules, the speculation claim, and `record_operator_write` (the
version bump plus speculation promotion). `web/compare.py` only renders and schedules.

`research/batch.py` takes a typed `BatchProgress` instead of a `MutableMapping`. Both
live under `api/app.AppState` at `app.state.live`, read through `api/deps.app_state`
the way `app_deps` reads `AppDeps`.

`_jev_read_label` was deleted: the compare template never rendered Jev's read (a test
asserts it stays hidden). `tests/test_web.py` and `tests/test_intake_queue_web.py` are
now `tests/web/` (one file per feature, with shared fixtures in `conftest.py` and
builders in `helpers.py`).

## H. Mirror the test tree to `src/` and consolidate builders — *done* in [#3](https://github.com/mr-mcox/koi/pull/3)

Tests now sit in folders mirroring `src/screen/` (`api/`, `compare/`, `digest/`,
`extract/`, `intake/`, `research/`, `research_trace/`, `score/`, `store/`, `verdict/`,
`web/`), each a package, with the `test_store_` prefixes dropped. Tests of top-level
modules (`types`, `pool`, `wiring`, `recalibration`, …), `rubric.yaml` and the import
layering stay at the top of `tests/`. Two files are named for what they cover rather than
a module: `test_pool_store.py` (pool assembly from the DB) and
`compare/test_picker_coverage.py`.

`tests/helpers.py` holds the builders: `canned_citation`, `canned_assertion(target, fit,
provenance, **overrides)` and `seed_opening(conn, opening_id, …)`, which derives the
company id, title and trace id from the opening id. They replace the per-file
`_assertion`/`_citation` builders, the `_seed_opening*` variants and the duplicates in
`tests/web/helpers.py`. Files whose default is ratified evidence bind
`partial(canned_assertion, provenance="ratified")`. The web tests and
`tests/api/test_routes.py` get a `conn` fixture.

What stays local on purpose: the dict builders in `test_types.py` (raw input for
validation tests), and `research/test_batch.py`'s `_seed_opening_with_trace` and
`_seed_assertions`, which combine the shared builders with a trace or bulk evidence.

## I. Comment pass — *done* at b932a5c and d3bf812

Docstrings and comments in `src/` now describe product state:
- Retired-CLI references are gone (`env.py`, `paths.py`, `intake/pipeline.py`,
  `research/batch.py`, `score/bandit.py`, `store/repo.py`, `web/intake_queue.py`), as is
  narration ("now", "before the feature", "loop fix", "the retired echo", "the prototype's
  gate", the `MutableMapping` progress dict that G replaced).
- Stale claims fixed: the picker's docstrings no longer give pair priority a closeness
  factor; `IntakeQueueItem` no longer says failed rows can't be retried; `research/actions.py`
  no longer says search and fetch are unimplemented; `run_batch` no longer caps a block by
  a per-opening budget; `repo.active_provisional_comparisons` names `_settled_pairs`; the Jev
  adapters point at the one omit list in `pyproject.toml`.
- The `Assertion` docstring is rewritten: its opening is repaired and it names
  `stats_for_target` instead of repeating the `0.3` confidence floor. `eligible_weights`
  names `bandit.boundary_weight` instead of restating a formula (the wrong one).
- Inline comments that narrated the next line were removed. Where code needed a comment,
  it now explains itself instead: `stats_for_target`'s confidence widening is
  `_confidence_widening` with a named `_CONFIDENCE_FLOOR`; `rank_pool`'s duplicated
  guarded/unguarded ranking blocks are `_sample_ranks` and `_rank_readouts`; `accepts`
  names `_BRIER_GAIN_PER_CHAR_SAVED` instead of commenting `/ 10000.0`;
  `UsablePair.expected` is typed `ComparisonOutcome` instead of commented. The section
  banners in `recalibration.py` and `types.py` are gone.

Left for M: the `eligible_weights` fallback sentence, which M's decision on that branch
rewrites or deletes.

## J. Coding-standard consistency — *open, last*

- Drop `from __future__ import annotations` (present in some files and not others; not
  needed on Python 3.14).
- Pick one Protocol naming style (`FooProtocol` vs `VerdictProvider`) and one
  protocol-file name (`protocol.py` vs `classification_protocol.py`).
- Replace the remaining untyped `dict[str, object]` / `dict[str, Any]` values in `src`
  (mostly template contexts in `web/`) with typed structures where a shape is known.

Touches: most of `src/`.

## K. Purge the salary figure from git history — *open, operator decision*

Commit 6deb320 removed the hardcoded baseline from the tracked files, but earlier commits
still contain it. Purging means rewriting `main` and force-pushing, which breaks
existing clones and forks. Because the repo is public, the figure may already have been
copied. Do this only on the operator's explicit go-ahead.

## L. Recalibration should read the digest the operator actually saw — *open*

Capture is complete and the history is intact; only the read path is unwired, so no
information is being lost — it just isn't used.

`Comparison.opening_a_digest_version`/`opening_b_digest_version` hold the
`DimensionDigest.id` shown at judgment time. Both recording paths populate them (the
operator form via the hidden fields in `compare.html`, the Jev provisional path in
`compare/prescreen.py`), `dimension_digests` is append-only with no update or delete, and
`repo.get_dimension_digest_by_id` resolves a superseded version correctly.

Nothing calls it. `recalibration.load_pairs` instead calls
`get_dimension_digest(conn, opening_id, target)`, which returns the *latest* digest, and
`scripts/backtest_jev_routing.py` does the same. Dispatch warms digests after every pass,
so a recalibration round run after new evidence replays Jev against a digest the operator
never saw while `expected` is their ruling against an older one. Those cases are
mislabeled, and the mismatch grows with evidence accumulated since the judgment.

- `load_pairs`: resolve each side by the recorded version via `get_dimension_digest_by_id`.
- Fall back to the latest digest only when the version is `NULL` — comparisons recorded
  before the field was threaded through. For those the pairing is unrecoverable.
- Return the fallback count alongside `shortfall` and surface it in the run record
  (`recalibration_run.py`), so a round built mostly on substituted digests says so rather
  than passing as clean evidence.
- Same resolution in `scripts/backtest_jev_routing.py`'s `_load_cases`.
- `migrations/0010_create_comparisons.sql` still calls the two columns "nullable
  placeholders … until then both stay NULL". They are populated; fix the comment.

Touches: `recalibration.py`, `recalibration_run.py`, `scripts/backtest_jev_routing.py`,
`store/migrations/0010_create_comparisons.sql`, the recalibration tests.

## M. Raise the coverage gate to 100% line and branch, with reasoned exclusions — *done* in [#5](https://github.com/mr-mcox/koi/pull/5)

`scripts/check.py` gates every file at 100% line and branch. `EXEMPT_FILES` and its
budget are gone, so `[tool.coverage.run] omit` in `pyproject.toml` is the only list of
excluded files; it now includes `src/screen/baml_client/`, so the reported total no longer
counts generated code. A new `pragma-reason` gate rejects a `# pragma: no cover` that
lacks a reason after a dash on the same line.

`browser.py` is tested through its `client=` seam: search's `content` →
`raw_content`/`snippet` mapping, SDK exceptions wrapped as retryable `BrowserError`s, and
the empty-response path. Its constructor needed no pragma, because one test already builds
a real `TavilyClient` without network I/O.

How each listed gap was closed:
- `ScoringConfig` now rejects a `boundary_weight_floor` outside (0, 1), so every boundary
  weight is positive. That made two branches dead, and both were deleted: the picker's
  `pair_priority <= 0` skip, and `eligible_weights`' fallback to raw uncertainty (which
  returned the same zeros). Its docstring's wrong `p_top_k * (1 - p_top_k)` formula and
  `top_k` example went with it.
- Deleted `PromptRubric.resolve()`, which had no callers. `IntakeQueueItem.id` lost its
  `default_factory` because the repo always supplies an id; the other models keep theirs,
  since those defaults do fire.
- `web/compare.py` resolves the distinct opening ids from a set, so there is no seen-check
  branch to test. A test could not have told the memo from repeated lookups.
- In the speculative prescreen, a step that doesn't commit returns `keep_going=True` only
  when the version moved, so the "keep going without committing" branch was unreachable.
  `_prescreen_step` now returns one `_StepOutcome` enum (`COMMITTED`, `STALE`,
  `STOPPED`) instead of a pair of bools, each of which only one caller read. The speculative loop
  ends after any step that doesn't commit.
- New tests cover the planner's 0-hit summary and `RunState.brier_noise_floor` (it must
  compare train against noise, not one run against itself).
- `baml_planner.last_context_text` renders the search context as its unconditional
  tail, so it needs neither `assert_never` nor a pragma. Pyright still fails if a new
  context type joins the union. `FakeTavily.search`'s pragma now gives a reason; N
  removes the method.

## N. Narrow the browser protocol and merge its two fakes — *open, after M*

`BrowserProtocol` (`browser.py`) is wider than any of its callers:
- `extract` is on the protocol, but no caller uses it through the protocol. Only
  `TavilyBrowser.fetch` calls it, internally. Drop it from the protocol, and make it
  private on `TavilyBrowser` unless a caller turns up.
- Intake only fetches (`intake/pipeline.fetch_url`, `intake_url`'s `client_factory`) but
  is typed against the whole protocol. That is why `FakeTavily.search` exists only to
  raise `NotImplementedError`, with an unused argument and a pragma. Give intake a
  fetch-only protocol, and let research's dispatcher keep `fetch` + `search`.

There are two fakes for the one seam. `intake/fakes.FakeTavily` takes Tavily-shaped
`extract` fixtures. `research/fakes.FakeBrowser` takes raw-content fixtures and records
calls. `tests/intake/test_pipeline.py` uses both. Keep one fake (`FakeBrowser` already
covers search and call recording), and move `FakeTavily`'s fixture semantics into it only
where a test needs them.

Tests that cover only the fakes, or a method that no longer exists, fail the AGENTS.md
test: none of them catches a regression in production code. Delete them, or name the
regression each one catches:
- `tests/test_browser.py`: the `FakeTavily` tests (satisfies the protocol, fetch returns
  a hit or raises, error details) and both `has_no_extract_one` tests.
- `tests/research/test_protocol.py`: `test_fake_browser_extract_records_calls`, and the
  `FakeBrowser` fixture tests.

Touches: `browser.py`, `intake/fakes.py`, `intake/pipeline.py`, `research/fakes.py`,
`research/dispatcher.py`, `research/batch.py`, `wiring.py`, `tests/test_browser.py`,
`tests/research/test_protocol.py`, `tests/intake/test_pipeline.py`, `tests/helpers.py`.

## O. Turn on pyright strict mode — *open, after M*

`[tool.pyright]` in `pyproject.toml` says "Strict mode turns on the full set of checks",
and `check.py` labels the gate "strict type checks", but `typeCheckingMode` is never set,
so pyright runs in its default mode. One consequence: a misspelled `Literal` in a
comparison (`outcome == "stoped"`) passes silently. `reportUnnecessaryComparison` catches
that, and strict turns it on.

Setting `typeCheckingMode = "strict"` reports 146 errors (as of PR #5). 103 are in
`recalibration_run.py`; `browser.py` has 13 and no other file more than 4. Nearly all are
`reportUnknown*`: values typed `Any` by `json.loads`, numpy, yaml and the Tavily
responses. Fix them by typing the data where it enters, e.g. parse
`recalibration_run.py`'s state into typed structures once on load. Don't scatter `cast`s
through the code.

- Set `typeCheckingMode = "strict"`, and fix the comment and the gate label so they
  describe the real config.
- Disabling a strict rule is a decision, recorded with its reason next to the setting.

Touches: `pyproject.toml`, `scripts/check.py`, `recalibration_run.py`, `browser.py`, and
the other files the errors name.

## P. Split `_prescreen_step` along its contract — *open, after M*

`compare/prescreen._prescreen_step` is private but has a contract its two callers depend
on, which breaks the AGENTS.md rule on private functions. Its callers read its outcome
differently: `run_prescreen` retries on `STALE`, while the speculative walk gives up and
also checks the version itself. `speculating_for` switches where an uncommitted result is
cached, and whether a commit updates `progress` and the operator cache. Nothing tests the
step on its own. The unreachable "keep going without committing" branch that M deleted
sat where those two contracts met.

Split it into:
- a side-effect-free step that picks the next suggestion and consults Jev, returning the
  suggestion, Jev's read, and the comparison to commit (if any), and
- the writes: append and bump the version, or cache for the operator or for speculation.

Each loop then owns its own policy when the version has moved. Test the pick-and-consult
step directly, and leave each loop's tests to cover its policy.

Touches: `compare/prescreen.py`, `tests/compare/test_prescreen.py`.
