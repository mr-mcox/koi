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
discarded; its learnings and decisions were kept. That inheritance lives in `docs/agent-briefs`:

| Doc | What it holds |
|---|---|
| `DOMAIN-MODEL.md` | Entities, bounded contexts, the seven walls (invariants), steel-thread order |
| `DECISIONS.md` | Durable decisions with status tags and the rejected alternatives |
| `LEARNINGS.md` | Prototype findings by pivot question, each claim evidence-graded |
| `OPEN-QUESTIONS.md` | Deliberately deferred questions, each with what would settle it |
| `PROTOTYPE-DECISIONS.md` | Appendix: the prototype's full decision record (D-numbers) |

**Reading order for a new session:** DOMAIN-MODEL → DECISIONS → whatever the task touches.

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
- **The walls are tests.** The invariants in `DOMAIN-MODEL.md` (raw positions never reach
  the scorer, non-scoring targets never enter standing, reach never sorts, …) are asserted
  structurally in the test suite. A change that breaks one should break a test, not
  silently change the model.
- **Rubric text is load-bearing.** Definitions are sliced verbatim into research prompts
  and review screens. Every rubric change carries a reason; the change log is an
  instrument, not bookkeeping.
- **The operator stays in the loop by design.** Route to them only what needs their
  judgment; batch what can be batched; never auto-close a judgment call on their behalf
  (precedent retrieves and shows, it does not decide).

## Privacy — this repo is public

Never commit, and keep gitignored from day one:

- The compensation baseline and any salary figures.
- The operator's extended résumé and any personal career detail.
- Contact names and warm-path/obtainability details (who the operator knows, and where).
- The evidence database and research transcripts — collected evidence names real
  companies and quotes real sources.
- API keys and all runtime secrets.

Real names of companies under evaluation never enter committed files. Docs use the
Company A–D pseudonyms defined in `docs/PROTOTYPE-DECISIONS.md`; committed examples and
test fixtures use synthetic or pseudonymized companies only. When in doubt, it goes in
untracked config or the data directory, not in git.

## Current phase

Walking skeleton, riskiest parts first. The steel thread (see `DOMAIN-MODEL.md`): one
opening entered by link → research pass writes assertions at company and opening level →
scorer bands it from provenance-widened distributions → the operator rules on entries →
re-score shows ratification narrowing. It exercises the three least-proven decisions —
the company/opening split, provenance-as-variance (S8), and the research-pass contract —
before anything is layered on them. Then: a few one-offs end-to-end, then batching to see
the ranking behave, then routing, precedent lookup, intake adapters, and the holding-area
view, in that order.

Build increments so problems surface immediately, not three layers up: each increment
should be exercised with real use (the operator screening a real opening) before the next
begins.
