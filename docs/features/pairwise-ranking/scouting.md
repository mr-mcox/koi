---
feature: pairwise-ranking
type: scouting
date: 2026-09-15
commit: 3a676c42c8f847be76358b4c7be74106e72cac75
---

## What We're Doing

The operator, after a few days of authentic use of the screener:

> "if the job says 'staff' it's unlikely to completely fail on the most critical rubric
> items. Location is ruling some positions out. And extractive business can sometimes be a
> slight problem. But realizing all of this is in degrees … what is happening is that I'm
> creating real gradients in my head re: where to put the dimension rulings — 'ooh, this
> one really would stretch me in interesting ways, so I'm going to put that more on the
> upper end of the positive scale. Hmm, that one is more generic but it's still staff
> level. So let's put that sorta positive but middle'."

> "I wonder if what I actually want to do is some sort of pairwise scoring rather than on
> X/Y per dimension. Compare opportunity A vs opportunity B on the stretch dimension. Pick
> which one is better or if they're tied. … Certainty comes with more evidence and then
> being a consistent winner."

> "The sort key really ought to be the ranking long term … What I'm effectively trying to
> do is get a sense of the current order and how much any given opening might change."

> "The 'which 5 are my front runners' is still north star. I want to keep a pipeline of
> companies to apply to fresh and get a sense of how much to continue working the ranking
> vs 'this is pretty settled, go for those'. A strong new opening messing with the ranking
> is just fine and expected."

> "I'm now thinking that 'contested review' should be deprecated and I should just rate on
> dimensions overall and can pop open the assertions to confirm or override as necessary."

> "A hybrid role is going to lose to a completely remote one. A remote role that
> acknowledges occasional travel to meet with the team is preferable to one that doesn't
> mention that at all. A fully remote company is going to beat one that has a central
> office but is hiring remotely. Could be that this is a rubric change too."

Restated for clarity, the feature has four parts:

1. **Pairwise comparisons replace the dimension-ruling pad.** Per dimension, the operator
   judges opening A vs opening B: A, B, or tie. Sides are randomized.
2. **The Scorer ranks the pool.** Assertions set each opening's prior; comparisons update
   it jointly across openings. The sort key becomes rank-based (`P(rank ≤ K)`), with a
   per-opening rank band and a top-K settledness signal.
3. **A pair picker** chooses which pair and which dimension to ask about, aimed at the
   top-K boundary, and routes unexamined uncertainty to research instead.
4. **Location splits** into a kill-only constraint plus a new graded dimension (rubric
   change).

Explicitly deferred: a digest-similarity prior (F52).

## Findings

### Operator framing and agreements

- **F1** — operator — north star is "which 5 are my front runners"; the ranking should
  show the current order, how far each opening could plausibly move, and whether the
  top 5 is settled enough to act on. A strong new opening reshuffling the ranking is
  expected, not a defect.
- **F2** — operator — the sort key should be rank-based long term, replacing
  `P(overall > bar)` (→ F10).
- **F3** — operator — assertions setting the prior is acceptable "if it's truly needed
  and/or to validate that this new approach works temporarily". It is needed permanently
  for two reasons: a fresh opening has zero comparisons and can only enter the ranking
  through its assertions (→ F1 "pipeline … fresh"), and constraints multiply quality on a
  fixed scale (→ F13).
- **F4** — operator — comparisons are per dimension: A better, B better, or tie.
  Certainty is not stated by the operator; it comes from evidence volume and consistent
  wins. The `settledness` input goes away.
- **F5** — operator — accepted model shape (conversation 2026-09-15), in place of plain
  Elo (fixed step size, no uncertainty, result depends on comparison order):
  - Latent value θ per opening per dimension.
  - Prior `N(m, (hw/√3)²)` from the existing assertion `TargetStats` (variance-matched to
    today's `Uniform(m ± hw)`).
  - Thurstone/probit likelihood per comparison: a win is `Φ((θ_win − θ_lose)/β)`, a tie is
    `√(Φ(d/β)·Φ(−d/β))` (peaks at zero difference, no extra dial).
  - One batch Laplace fit per dimension across the pool (Newton to the MAP, Hessian
    inverse as covariance) → a mean vector plus a covariance matrix.
  - `β` is a new named `scoring.yaml` dial, an unmeasured placeholder like `bar`
    (`scoring.yaml:13`), later fit from the calibration log (→ F33).
- **F6** — operator, shown in conversation — in a toy two-opening run (prior N(0.6, 0.5²),
  β=0.5), P(B>A) went 0.49 → 0.80 → 0.96 after 0 / 1 / 3 B wins, while each opening's own
  sd only went 0.50 → 0.44 → 0.42. **Confidence from comparisons lives mostly in the
  covariance.** Monte Carlo must draw dimension values jointly (multivariate normal), not
  from per-opening marginals, or that confidence is thrown away.
- **F7** — operator — deprecate contested review. The operator rates dimensions overall
  via comparisons and pops open assertions to confirm or override as needed.
- **F8** — operator — the comparison screen shows both openings' dimension digests and
  their assertions (expandable, with confirm/override inline). Sides are randomized per
  comparison.
- **F9** — operator — halo is a known, accepted risk, especially for name-brand companies.
  Per-dimension framing and randomized sides are the mitigations; no name redaction is
  required.

### Current scoring terrain

- **F10** ⚠ — decisions S1 — the queue sorts on `P(value > bar)`. F2 supersedes this; a
  new S-decision is required, and S1's rejections (point estimates,
  confidence-as-multiplier, unknowns-as-zero) must carry forward into it.
- **F11** — `src/screen/score/scorer.py:159` — `score()` takes one opening's assertions
  and returns one `ScoreResult`; nothing from other openings enters. Dimensions are sampled
  `Uniform(mean ± half_width)` (`scorer.py:104-105`); constraints map onto tolerability
  ranges (`scorer.py:108-115`) and multiply quality (`scorer.py:193-195`).
- **F12** ⚠ — domain-model §Scorer — the Scorer is defined as a pure
  `(assertions, rubric) → per-target distributions → trace → standing, reach, ceiling`,
  stateless and per opening. Under F5 an opening's posterior depends on other openings'
  comparisons: the Scorer becomes pool-scoped. Per-opening call sites that would change:
  `src/screen/api/scoring.py:36` (`score_opening`), looped in
  `src/screen/web/routes.py:238-252` and `src/screen/api/routes.py:104-118`.
- **F13** — decisions S2; `scorer.py:193-195` — `overall = quality × Π tolerability`. A
  multiplier only means something against quality on a fixed scale; a pairwise latent has
  no fixed zero point, so it cannot replace the assertion prior (→ F3).
- **F14** — `src/screen/score/types.py:61-95` — `ScoreResult.standing` counts trace
  samples above `bar`; `unreachable` is `ceiling <= bar`. Both are bar-keyed.
- **F15** ⚠ — decisions S4 — the cliff is analytic against `bar`. The conversation's
  relative restatement: an opening is over the cliff when its analytic ceiling is below
  the K-th opening's analytic floor. It needs a decision entry.
- **F16** [x] ⚠ — decisions S5; domain-model walls 7; `api/scoring.py:49-50`;
  `scorer.py:224` (`resolve_favourably`) — `reach` is `P(> bar)` under a favourable
  counterfactual pass. There is no rank-based definition yet. Open: retire `reach`,
  or redefine it (e.g. best plausible rank after one favourable pass on each unexamined
  target)? Wall 7 ("reach never becomes a sort key") holds either way. **Resolved:** retire reach (F68) → rank-pool.md §Agreed.
- **F17** — `src/screen/score/boundary.py:20-30` — `crossing_probability` already
  approximates `P(rank crosses K)` by comparing an opening's trace elementwise against the
  K-th opening's trace, and its docstring admits it treats the K-th as a fixed reference.
  Consumers: `web/routes.py:285`, `web/routes.py:309`, `web/routes.py:431`,
  `api/routes.py:127-136`. Joint pool Monte Carlo makes it redundant.
- **F18** — `src/screen/score/interval.py:22`; `src/screen/web/templates/_boundary_glyph.html`;
  `api/scoring.py:24-28` — the queue glyph plots q10/median/q90 of the `overall` trace on
  the score axis, not the rank axis.
- **F19** — `web/routes.py:254`; `api/routes.py:120` — two sort sites, both on `standing`.
- **F20** — `scoring.yaml:71` — `top_k: 5` exists as an unmeasured placeholder.
- **F21** [!] — proposed in conversation, not objected to — ranking readouts:
  - sort on `P(rank ≤ K)`, tiebreak on expected rank (the tail is all ~0, the same way
    `P(> bar)` never gave a total order — decisions §Deleted);
  - per-opening rank band q10–q90 (e.g. "#3, could be #2–#7");
  - top-K settledness = expected overlap between a sampled top-K and the current top-K
    (e.g. 4.7/5 "go apply", 3.2/5 "keep comparing").
  → Recalibrate When the settledness number disagrees with the operator's gut about
  whether the top 5 is settled.
- **F22** — decisions S6; domain-model walls 4 — no false precision in display. A rank
  band satisfies this; a decimal `P(top K)` on the queue would not.
- **F23** [x] — proposed in conversation, not explicitly answered — move every
  dimension to Gaussians (one distribution family, matching F5), with constraints keeping
  their bounded tolerability ranges. This changes tail behavior even for dimensions that
  have never been compared. **Resolved:** switch all dimensions to Gaussian (F83) → rank-pool.md §Agreed.
- **F24** — `tests/test_scorer.py:121` (`test_order_independent`) — order independence is
  asserted in tests. A batch Laplace fit keeps it; online updates (Elo, single-pass
  TrueSkill) would break it.
- **F25** — `pyproject.toml` dependencies — numpy is the only numeric dependency; there is
  no scipy. Φ and the Newton/Hessian fit must be numpy/`math.erf`, or a dependency must be
  added.
- **F26** — domain-model §Scorer — "the trace is the source of truth". Pool Monte Carlo
  produces an openings × samples matrix; ranks are computed per sample column.
- **F27** [!] — operator (earlier in conversation) — dropping `bar` as the sort key means a
  pure ranking always yields a top K, even from a weak pool. Acceptable with a fresh
  pipeline (and consistent with decisions S2's "lots of fish"). A display-only floor stays
  optional. → Recalibrate When the live pool thins to fewer than a handful of openings a
  week.
- **F28** [!] — operator — "Ok if it's truly needed and/or to validate that this new
  approach works temporarily." Proposed validation: run the rank-based ordering alongside
  today's `P(> bar)` ordering, plus the calibration log (F33). → Recalibrate When the
  model's pre-comparison predictions are persistently miscalibrated. Side-by-side half superseded by F81.

### Pair and dimension selection

- **F29** [!] — proposed, not objected to — pair choice v1 (LUCB-style top-K selection):
  the opening inside the top K with the lowest plausible value vs the opening outside with
  the highest plausible value. A fresh opening's wide upside pulls it into a boundary
  comparison immediately; an opening that can't reach the top K is never asked about.
  v2 (expected information gain over a v1 shortlist) only if v1 asks poor questions.
  → Recalibrate When v1 repeatedly offers pairs the operator finds obviously settled.
- **F30** — operator (agreed) — dimension choice by variance share, roughly
  `w_d² · (constraint scaling) · Var(θ_i,d − θ_j,d)`. A tie on one dimension shrinks that
  dimension's share, so the next question moves on (e.g. stretch → trajectory). The same
  breakdown per opening gives a "what's moving this rank" readout.
- **F31** — operator (agreed) — compare-vs-research routing: compare on dimension d only
  when both openings have evidence (assertions and a digest) on d. Uncertainty that is wide
  because a dimension is unexamined routes to research. This keeps
  domain-model walls 5 ("unexamined ≠ clean") and decisions S3.
- **F32** — decisions W3 — VOI means "would this change what happens". Boundary-focused
  pair picking (F29) and routing (F31) both implement it.
- **F33** — operator (agreed) — calibration log: before each answer, record the model's
  `P(A beats B)`. It validates the approach (F28) and later calibrates `β` (F5). It is the
  pairwise form of the ruling corpus (domain-model §Ruling: "the accumulating corpus is
  the calibration data for everything").
- **F34** — `data/live/screen.db` (`openings`, `assertions` schema) — 32 openings in
  `screening`; 3 companies have more than one screening opening. The `assertions` table
  has only `opening_id` (no company-level rows), even though domain-model §Company lists
  company-level targets (mission, trajectory, peer, agentic, domain, internal_culture,
  extractive_business) and decisions E4 separates companies from openings.
- **F35** [x] — two openings at the same company compared on a company-level dimension:
  skip the pair, auto-tie it, or allow it? **Resolved:** auto-tie (F70) → compare.md §Agreed (pending).
- **F36** [x] — which dimensions are comparable in v1? Conversation proposed the two
  weight-3 dimensions first (`rubric.yaml:112` stretch, `rubric.yaml:161` schematic).
  Compensation (`rubric.yaml:298-313`) is anchored to a private baseline (decisions R3)
  and is factual; domain (`rubric.yaml:314-332`) is operator reaction only
  (domain-model §Company). **Resolved:** every dimension is comparable, compensation and domain included (F71) → compare.md §Agreed (pending).
- **F37** [!] — proposed, not objected to — constraints are never compared pairwise; they
  stay absolute multipliers (decisions S2). Made cleaner by the location split (F59).
  → Recalibrate When the operator finds themselves wanting to compare constraint
  situations.

### Research coupling

- **F38** — `src/screen/research/baml_planner.py:70-115`; `src/screen/research/state.py:40-42`;
  `src/screen/research/batch.py:168` — the research planner reads
  `DimensionRuling.settledness` to rank targets within an opening. Retiring rulings
  removes that input; the assertion-count fallback already exists
  (`baml_planner.py:96-97`).
- **F39** — `src/screen/research/batch.py:277-287`; `src/screen/score/bandit.py:19-40` —
  the research draw weight per opening is the aggregate dimension-weighted half-width,
  including dimension rulings. It does not look at the top-K boundary.
- **F40** [x] — proposed as a knock-on, not agreed — change the research draw weight to
  boundary-weighted `P(top K) · (1 − P(top K))` in this feature, or leave it for later? **Resolved:** in this feature (F73) → research-targeting.md §Agreed (pending).

### What retires

- **F41** — operator — drop existing dimension rulings; backward compatibility isn't
  worth it. Stop reading them. (The conversation suggested leaving the rows in place
  rather than deleting data.)
- **F42** — `DimensionRuling` surface:
  - model: `src/screen/types.py:199-224`
  - migrations: `0005_create_dimension_rulings.sql`, `0007_add_dimension_ruling_covered_assertion_ids.sql`
  - store: `src/screen/store/repo.py:188-213`, `src/screen/store/mappers.py:138-160`
  - scorer: `scorer.py:118-158` (`_dimension_ruling_stats`, `stats_for_target`)
  - config: `scoring.yaml:58` (`dimension_ruling.hw_max/hw_min`),
    `src/screen/score/loader.py:67-68`, `src/screen/score/types.py:48-49`
  - web: `src/screen/web/routes.py:654-703` (submit),
    `src/screen/web/templates/_rating_content.html:13-30` (pad),
    `src/screen/web/static/dimension-ruling-pad.js`
  - CLI: `src/screen/intake/cli.py:66-104` (`backfill_dimension_ruling_covered_assertion_ids`)
  - API glue: `src/screen/api/scoring.py:74-80`, `src/screen/api/routes.py:86-91`, `src/screen/api/routes.py:104-118`
- **F43** ⚠ — domain-model §Ruling — records as *settled* that rulings are siblings
  `AssertionRuling` (categorical) and `DimensionRuling` (continuous `(mean, settledness)`).
  This feature replaces the second with a comparison record, so the settled text must be
  rewritten, not just extended.
- **F44** — domain-model walls 1 (asserted at `tests/test_types.py:172`) — raw plane
  positions never reach the Scorer. Comparisons are discrete outcomes that enter as a
  likelihood, not a continuous confidence next to a multiplication, so they are consistent
  with the wall's rationale. Wall 2 (fit and provenance never blend) is untouched.
- **F45** — `src/screen/web/routes.py:297-315`, `routes.py:354-383`;
  `src/screen/web/templates/queue.html:14`; `src/screen/web/templates/rating.html:21-24` —
  contested review orders openings by `crossing_probability`, filtered to those with
  rating leverage. Retires per F7.
- **F46** — `src/screen/score/triage.py` — `rating_task_candidates` computes swings for
  assertion tasks and dimension-ruling tasks. The dimension half retires with rulings.
  Consumers: `web/routes.py:320-331` (`_opening_leverage`), `web/routes.py:406-409`,
  `web/routes.py:481-496`; `scoring.yaml:66` `rating_task_budget`.
- **F47** [x] — `src/screen/web/routes.py:587-611` (`/openings/{id}/focus`),
  `routes.py:334-344` (`_focus_queue_items`) — the per-opening focus session ranks by
  rating leverage, including dimension tasks. Not addressed by the operator: retire it,
  or keep it as an assertion-only focus view? **Resolved:** retire it (F74) → rank-pool.md §Agreed.
- **F48** — test blast radius, from grep counts of `DimensionRuling|dimension_ruling`:
  `tests/test_scorer.py` 27 (tests at lines 145–281), `tests/test_web.py` 28,
  `tests/test_triage.py` 12, `tests/test_baml_planner.py` 6, `tests/test_api_scoring.py` 5;
  `contested` appears 21 times in `tests/test_web.py`.

### Comparison storage and digests

- **F49** — `src/screen/store/repo.py:158-186`; `src/screen/digest/service.py:42-70` —
  `dimension_digests` is keyed `(opening_id, target)` and upserted in place whenever an
  opening's assertion count for that target grows. **No digest history exists.** The
  operator believed snapshots already existed; they do not.
- **F50** — operator (agreed) — each comparison references the exact digest version shown for
  both openings (digest history kept, corrected per F76), so what was compared can be reconstructed and a future similarity
  prior has training data.
- **F51** [x] — `src/screen/store/repo.py:88-91` — `AssertionRuling` upserts one row per
  assertion ("a calibration record … not an event log"). Comparisons need a policy: is
  every comparison appended and counted, or is the latest judgment kept per
  (unordered pair, dimension)? Repeating the same pair is not independent evidence, so
  counting every repeat would over-sharpen. The calibration log (F33) wants every event
  either way. The next migration number is `0010`
  (`src/screen/store/migrations/0009_create_intake_queue.sql`). **Resolved:** keep full history (F75) → compare.md §Agreed (pending).
- **F52** — operator — deferred, "may never need it": a similarity prior. Replace the
  diagonal prior covariance with a kernel over digest embeddings, so opening Y's wins
  lift a similar opening Z. No new inference beyond F5's fit. Its validation is whether it
  improves prediction in the calibration log (F33).
- **F53** ⚠ — decisions W5 — "precedent retrieves and shows; it never decides". A
  similarity prior moves scores. Deferred and out of scope, but when it is built it needs
  a decision entry placing it on decisions S8's `precedent_matched` rung rather than
  auto-close.

### Constraints and location

- **F54** — `rubric.yaml:26-48` — location situations today: remote any (1.0);
  hybrid/onsite same metro, bikeable (1.0); different metro (0.15–0.95); relocation
  required (0.02–0.10); not examined (0.0–1.0).
- **F55** — `data/live/screen.db` (`assertions` where `target='location'`) — 40 location
  assertions: 1 Poor, 19 Mixed, 20 Strong. "This role must be physically based in China",
  "San Francisco, CA", "United States" and "US - Remote Eligible … occasional work at an
  Airbnb office" are all `Mixed`.
- **F56** — open-questions 14 — its settling condition: "If it visibly misreads a real
  case, that's the evidence to switch constraints to collecting a situation label instead
  of `Fit`." F55 meets it.
- **F57** — domain-model §Scorer — records the same tension: `Assertion` has no
  situation-label field (`src/screen/types.py:171` carries `target`/`fit` only), so
  collecting labels is a schema change.
- **F58** — operator — location preference ordering: fully remote company > remote role
  that acknowledges occasional team travel > remote role that doesn't mention travel >
  remote role at a company with a central office > hybrid. Hybrid loses to fully remote.
- **F59** — operator (agreed) — split location into:
  - a kill-only constraint answering "can this physically work" (US-remote or bikeable
    vs. relocation or another country);
  - a new graded, pairwise-comparable dimension (working name `distributed`) holding the
    F58 ordering.
- **F60** — `rubric.yaml:74-93`; `rubric.yaml:256` — the precedent pattern:
  `extractive_business` covers "clear-cut anchor cases only", and nuance "flows into the
  Mission fit dimension".
- **F61** — decisions R4; `AGENTS.md` "Rubric text is load-bearing" — every rubric change
  carries a reason (F55 is that reason). A new dimension also touches the hand-listed
  `Target` Literal (`src/screen/types.py:103-116`, wall 3, `tests/test_rubric.py:91`) and
  the BAML schema (open-questions 13).
- **F62** [x] — operator-owned: the new dimension's weight, and its final slug. **Resolved:** `distributed` accepted; weight still to set (F77) → constraints-and-rubric.md §Agreed (pending).
- **F63** [x] — does the kill-only location constraint switch to collecting situation
  labels (F56–F57) in this feature, or keep `Fit` with rewritten anchors for now? **Resolved:** situation labels now (F78) → constraints-and-rubric.md §Agreed (pending).
- **F64** — `data/live/screen.db` (`dimension_rulings`) — internal_culture: 8 rulings, mean
  0.32, range 0.00–0.57, which is gradient use of a constraint. The operator deferred a
  similar split for internal_culture until location proves the pattern.
- **F65** — `data/live/screen.db` (`dimension_rulings`) — evidence behind F4: 49 rulings
  across 9 openings. Stretch means span 0.43–0.85, schematic 0.54–0.90, and settledness
  never falls below 0.19 or rises above 0.68 on any target. The pad is being used
  ordinally, within the positive half.

### Decision record

- **F66** — `AGENTS.md` "Decisions are append-only and carry their rejections" — this
  feature needs decision entries:
  - superseding S1 (sort key → F2, F21), S4 (cliff → F15), S5 (reach → F16);
  - rewriting domain-model §Ruling (F43) and §Scorer (F12);
  - recording rejections: plain Elo (order-dependent, no uncertainty), operator-stated
    settledness, a pairwise model without an assertion anchor (F3, F13), and online
    single-pass updates (F24).

### Resolutions and additions (2026-09-16)

- **F67** — `src/screen/web/templates/` (grep for `reach`/`unreachable`, no hits);
  `src/screen/api/routes.py:45-68` — `reach` and `unreachable` show up only in the JSON
  API's `ScoreResponse`. No page renders them, so retiring them touches no UI.
- **F68** — operator — retire `reach` (F16). Its job ("how much room remains") is covered
  by the rank band (F21) plus the variance-share breakdown (F30), which separates
  "wide because unexamined" from "wide because contested" (domain-model walls 5).
- **F69** [x] — `src/screen/score/scorer.py:197` (analytic ceiling inside `score()`) —
  the cost of switching to Gaussians (F23): today's bounded Uniform support is what makes
  decisions S4's cliff *analytic* ("no sample could clear"). A Gaussian has no upper
  bound, so the cliff would become "P(top K) below sampling resolution" or a chosen
  quantile. Unexamined also changes shape: flat Uniform(−1, +1) becomes a
  centre-weighted N(0, 0.577²). Open: switch anyway and retire the S4 cliff? **Resolved:** switch and drop the cliff (F83) → rank-pool.md §Agreed.
- **F70** [!] — operator — two openings at the same company auto-tie on company-level
  dimensions (F35). Proposed mechanics: an implicit tie term in the likelihood, generated
  rather than stored as an operator comparison, and excluded from the calibration log
  (F33). → Recalibrate When same-company openings visibly diverge on a company-level
  dimension.
- **F71** ⚠ — operator; decisions R3; `rubric.yaml:298-313` — compensation is judged as
  "the likelihood that if I get it, my total compensation would be higher", with some
  squish (private vs. public equity, vesting schedule). R3 ("a single configured
  baseline") and the compensation definition need rewriting. The baseline can still anchor
  the assertion prior (F3).
- **F72** [!] ⚠ — domain-model §Company ("domain coolness … manual entry only, never
  researched"); F31 — domain gets no researched assertions, so the compare-only-with-
  evidence rule would never compare it. For domain the operator *is* the evidence.
  Proposed: exempt domain from F31's evidence requirement. → Recalibrate When another
  dimension turns out to be operator-reaction-only.
- **F73** — operator — do the research reweighting (F40) in this feature. Terrain: it
  wouldn't crash after rulings retire; `bandit.py:19-40` and `baml_planner.py:96-97` fall
  back to assertion half-widths. But it would keep spending research on openings that
  can't reach the top K, which contradicts F1.
- **F74** — operator — retire the focus view (F47), along with `rating_task_budget`
  (`scoring.yaml:66`) and the dimension-task half of `triage.py` (F46).
- **F75** [!] — operator — comparisons are append-only with full history (F51). Proposed
  fit policy: the model fits on the latest judgment per (unordered pair, dimension), since
  a repeat isn't independent evidence and a changed mind should win; the calibration log
  uses every event. → Recalibrate When the operator repeats a pair intending the repeat to
  strengthen the evidence.
- **F76** — operator — digests also keep history. Digest versions are append-only, and
  each comparison links to the digest versions the operator saw. This replaces the
  in-place upsert (F49) and corrects F50's "store the text" shape.
- **F77** [x] — operator — `distributed` accepted as the new dimension's slug (F62). Its
  weight is still unset (`rubric.yaml` weights today: 3, 3, 2, 2, 2, 2, 2, 1). **Resolved:** weight 5 (F84) → constraints-and-rubric.md §Agreed (pending).
- **F78** [x] — operator — constraints switch to collecting situation labels now (F63),
  not `Fit` with rewritten anchors. Open: all three constraints, or location only? The
  Fit→tolerability bridge (`scorer.py:108-115`) serves all three. **Resolved:** all three (F85) → constraints-and-rubric.md §Agreed (pending).
- **F79** ⚠ — domain-model walls 6; `data/live/screen.db` — 107 existing constraint
  assertions (location 40, internal_culture 39, extractive_business 28) carry `Fit`, not
  labels, and assertions are append-only. Under label scoring they are ignored, so those
  constraints read as unexamined until re-researched. Across the 32 screening openings
  that is a research-budget event, not a migration.
- **F80** — operator — overall theme: "rip off the bandaid now and make the fixes rather
  than having it be more complicated and support what's going to be incompatible in the
  long run." No compatibility layers or dual paths for anything retiring.
- **F81** [!] — F80 applied to F28 — no side-by-side `P(> bar)` ordering. The calibration
  log (F33) is the validation instrument. → Recalibrate When the first ~20 comparisons'
  predictions look miscalibrated, before building more on the fit.
- **F82** — operator — this may split into multiple bearings; open to a steel-thread
  proposal.
- **F83** — operator — drop the cliff; switch every dimension to Gaussian (F23, F69).
- **F84** — operator — `distributed` weight is 5: "we aren't going to move and it affects
  quality of workplace a lot". It becomes the heaviest dimension; total weight goes from
  17 to 22.
- **F85** — operator — all three constraints collect situation labels (F78). Constraints
  reading as unexamined until re-researched is acceptable (F79).
- **F86** — docs/architecture/discipline.md — per function: complexity ≤ 7 and ≤ 50 lines;
  per file: ≤ 200 lines; gated in `scripts/check.py`. A pool-scoped Scorer (F12) has to
  fit these limits.
