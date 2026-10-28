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

## G. Split `web/routes.py` by feature and type the app's mutable state — *open, after E*

`web/routes.py` is about 1,000 lines covering five features: queue/rating, compare, archive,
batch, and intake queue. It also holds compare business rules (staleness rejection,
speculation promotion, suggestion legality) that belong with F's compare package.

- Split the routes into one module per feature under `web/`.
- Move the compare decisions into `compare/` (F created it).
- Replace the untyped `app.state.batch_status` dict and `progress: MutableMapping` in
  `research/batch.py` with a typed dataclass (the unused `BatchProgress` in
  `research/batch.py` is a starting point), and expose the mutable state the way
  `api/deps.app_deps` exposes `AppDeps`.
- Split `tests/test_web.py` (about 2,400 lines) to match.

Touches: `web/`, `api/app.py`, `api/deps.py`, `research/batch.py`, `tests/test_web.py`.

## H. Mirror the test tree to `src/` and consolidate builders — *open, after F and G*

`tests/` holds 56 files flat.
- Move tests into folders mirroring `src/screen/`.
- Drop the redundant `test_store_` filename prefixes.
- Add `__init__.py` to `tests/intake/` to match its sibling folders.
- Replace the 17 per-file `_assertion` builders and the `_seed_opening*` variants with
  shared builders in `tests/helpers.py`.

Touches: every test file.

## I. Comment pass — *open, last*

Apply the AGENTS.md rule that comments describe product state, not history.
- A docstring never restates a value or formula that lives in code or config; it names
  it instead. For example, the `Assertion` docstring in `types.py` repeats the `0.3`
  confidence floor.
- Remove narration of how the code got here: "now", "previously", "before the
  feature", which slice added it.
- Remove comments that repeat their own docstring.
- Fix the garbled opening of the `Assertion` docstring.

Touches: most of `src/`.

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

## M. Raise the coverage gate to 100% line and branch, with reasoned exclusions — *open, after G*

The per-file gate in `scripts/check.py` is 95% line and branch. That slack lets a file
carry untested lines without anyone deciding whether they are dead, defensive, or real
logic missing a test. At 100%, every uncovered line ends in one of three places: a test
that catches a nameable regression, deletion, or an explicit exclusion with a reason. The
`omit` list then becomes the single reviewable statement of what touches the outside world.

Gate changes:
- `COVERAGE_TIER_PERCENT = 100` in `scripts/check.py`.
- Allow `# pragma: no cover` only with a reason on the same line
  (`# pragma: no cover — <why>`); add a `check.py` gate that rejects a bare pragma, the
  same way it rejects `type: ignore`. Use it for lines a test can't reach without
  testing the harness: `assert_never` exhaustiveness guards, true thread-timing windows,
  and the live-default half of an injectable constructor (`client if client is not None
  else TavilyClient(...)`).
- Add `src/screen/baml_client/` to `[tool.coverage.run] omit`. `check.py` already exempts
  it from the per-file gate, but it still dilutes the reported total (88% vs. near 100%
  for first-party code).
- Remove `browser.py` from `EXEMPT_FILES`. The file-wide exemption hides pure logic:
  `search()`'s Tavily field mapping (`content` → `raw_content`/`snippet`, `title`),
  `fetch()`'s retry and permanent-failure path, and `_fetch_once`'s
  results/failed/empty branches. The constructor already takes `client=` and `sleep=`,
  so a fake client covers all of it; only the default `TavilyClient(...)` construction is
  live.

Gaps to close (as of 670cd18; line numbers will move under F and G). For each, decide
test or delete:
- `extract/prompt.py` `PromptRubric.resolve()`: never called. Delete unless a
  recalibration path is meant to use it.
- `types.py` `id` `default_factory`: never fires because every caller supplies an id.
  Drop the default, or test the path that relies on it.
- `compare/picker.py` `if pair_priority <= 0.0: continue`: reachable only with
  `boundary_weight_floor == 0`. Delete if the config forbids 0; otherwise test it.
- `recalibration_run.py` `brier_noise_floor`: property never read in tests.
- `web/routes.py`: the Jev "tie" gloss, the speculation-already-in-flight guard, and the
  "opening already seen" `continue` in the provisional-comparison loop.
- `compare/prescreen.py`: the speculative walk taking a non-commit step and continuing.
- `research/baml_planner.py`: the 0-hit search summary.
- `research/batch.py`: the fallback to raw uncertainty when every boundary weight is zero.

Touches: `scripts/check.py`, `pyproject.toml`, `browser.py`, the files above, their
tests.
