# AGENTS.md — Job Screener (Clean Build)

*This file orients any agent (or future human) working in this repo. It is pointers, not
copies — the referenced docs are authoritative, and duplicating their content here is how
drift starts.*

## What this is

A decision-support system for a job search, built and used by one person (**the
operator**), and published as a portfolio project. It does three things:

1. **Gathers evidence** — an agentic research pass collects granular, source-cited claims
   about companies and job openings against a weighted rubric.
2. **Ranks under honest uncertainty** — openings are scored as probability distributions
   (Monte Carlo) and sorted by `P(value > bar)`, so a promising unknown outranks a
   well-documented mediocrity and every number knows how little it knows.
3. **Calibrates against the operator** — the system's job is to predict what the operator
   would conclude; their rulings are the calibration corpus, and their attention is the
   scarcest resource, spent only where the model can't substitute.

The core value is **strategic use of the operator's time and attention**: signal through
noise, the most promising opportunities rising, research effort aimed where it changes
outcomes. It is deliberately *not* a to-do generator, an application tracker, or an
auto-apply bot.

This repo is a clean build seeded from a working prototype. The prototype's code was
discarded; its learnings and decisions were kept. That inheritance lives in `docs/architecture`:

| Doc | What it holds |
|---|---|
| `domain-model.md` | Entities, bounded contexts, the seven walls (invariants), steel-thread order |
| `decisions.md` | Durable decisions with status tags and the rejected alternatives |
| `learnings.md` | Prototype findings by pivot question, each claim evidence-graded |
| `open-questions.md` | Deliberately deferred questions, each with what would settle it |
| `prototype-decisions.md` | Appendix: the prototype's full decision record (D-numbers) |

**Reading order for a new session:** domain-model → decisions → whatever the task touches.

## Orientation — how work is done here

- **No unearned precision.** This is the house epistemology and it is load-bearing: a
  single review must never produce "6.7/10"; precision is for ranking, bands are for
  display; unexamined is never conflated with clean; claims carry evidence grades. When
  proposing a mechanism, show the math and a worked table — a numeric demonstration that
  an approach can't work ends debates that argument doesn't.
- **Measure before model.** A cost model fitted to no data is a guess with decimal places.
  When a number is needed and unmeasured, it is a named config value the operator owns,
  not a constant hidden in code.
- **Decisions are append-only and carry their rejections.** Before proposing changes to
  scoring, read the S-decisions — confidence-as-multiplier has been rejected three times
  and gates-as-weights was killed by measurement. Record new decisions in the same form:
  what, why, what was rejected, status tag.
- **The walls are tests.** The invariants in `domain-model.md` (raw positions never reach
  the scorer, non-scoring targets never enter standing, reach never sorts, …) are asserted
  structurally in the test suite. A change that breaks one should break a test, not
  silently change the model.
- **Rubric text is load-bearing.** Definitions are sliced verbatim into research prompts
  and review screens. Every rubric change carries a reason; the change log is an
  instrument, not bookkeeping.
- **The operator stays in the loop by design.** Route to them only what needs their
  judgment; batch what can be batched; never auto-close a judgment call on their behalf
  (precedent retrieves and shows, it does not decide).
- **monkeypatch rarely; DI almost always.** Tests plug dependencies in via the constructor
  or argument list, not via `monkeypatch.setattr`. If a test needs a deterministic value for
  a clock, an env var, a setup fixture, the production code takes a parameter for it and the
  test passes a literal. monkeypatch is acceptable only when the seam is fixed (a third-party
  class with no injection point, a `CliRunner.invoke` that won't swap a module global) and
  refactoring for testability would distort the implementation; document the reason inline
  and revisit when a DI hook appears.
- **Tests catch named regressions; invented tests are removed.** A test that passes against
  a deliberately broken version of its subject is a test of the harness, not of the
  behavior. The check is mechanical: when reviewing a test, name one regression it would
  catch. If you can't, delete it.
- **Comments describe product state, not journey.** A comment should explain the non-obvious
  *why* — invariants the next reader can't derive, constraints imposed by external
  dependencies, the shape of required caller behavior. It should not narrate how the code
  came to be, what was considered and rejected, which slice introduced the function, or the
  rationale trace leading to the current form.
- **Every item here earns its space.** This file is read at the start of every agent session;
  size is paid per read, not per author. Each entry must either prevent a failure mode the
  agent would repeat without it, or preserve a constraint the agent can't derive. Entries
  that don't earn their space are removed. The standard is the formula
  `quality = correctness² × completeness / size` — correctness squared because a small
  correctness drop in operator-facing outputs is catastrophic; completeness replacing the
  spec with the actual product; size as cost paid.

## Privacy — this repo is public

Never commit, and keep gitignored from day one:

- The compensation baseline and any salary figures.
- The operator's extended résumé and any personal career detail.
- Contact names and warm-path/obtainability details (who the operator knows, and where).
- The evidence database and research transcripts — collected evidence names real
  companies and quotes real sources.
- API keys and all runtime secrets.

Real names of companies under evaluation never enter committed files. Docs use the
Company A–D pseudonyms defined in `docs/prototype-decisions.md`; committed examples and
test fixtures use synthetic or pseudonymized companies only. When in doubt, it goes in
untracked config or the data directory, not in git.
## Ready to commit
`uv run python scripts/check.py` runs the project gates. On failure
each gate prints its iterate-from-fix command.

## Current phase
Walking skeleton, riskiest parts first.
begins.
