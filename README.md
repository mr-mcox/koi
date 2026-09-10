# koi

**K**epler **O**bjects of **I**nterest <- Those are the stars Kepler flagged because something dimmed
them a little, and interestingly, do so according to a predictable pattern. Most of them turn out to be a bad pixel, or
a smudge on the instrument. A few are planets. An underwhelming minority are planets somewhere you could
imagine living. The entire discipline is deciding which is which from a signal that is mostly
noise, without the luxury of going to look.

The job market is brutal right now, and it turns out to have roughly the same shape. Forty
postings dim your attention a little. Most are nothing. You can't go and look at all of them.
So I built myself a telescope.

koi takes a job posting, researches the company behind it, and ranks openings by the
probability they're worth my time, while staying honest about how little it knows. Openings
are candidates, never discoveries. The whole job is disposition under uncertainty.

**Fair warning.** This is built for exactly one person, and that person is me. My rubric, my
weights, and my tolerance for a hybrid role in the wrong metro. You can absolutely run it. It
works from a clean checkout and the setup is a couple of commands. But it will rank things
according to my priors, and I anticipate what's important to me probably doesn't work for you.
It's also got a bunch of my mindsets baked in. You might find that interesting enough that it's worth adapting for your purposes. If so cool. Or maybe you peek inside my brain and see a way of working that your team could benefit from. Also great.

---

## What it actually does

1. **Intake.** You paste a link. The only question intake answers is *is there a screenable
   unit here*. Out comes a Company and an Opening, or an explicit **unscreenable** record
   with a reason.
2. **Research.** An agentic pass searches and reads, filing granular claims against rubric
   targets. Each claim points at exactly one dimension, carries a verbatim quote and a URL,
   and never gets rewritten. Evidence is append-only.
3. **Scoring.** A Monte Carlo scorer turns those claims into distributions and sorts the queue
   on `P(value > bar)`.
4. **Review.** A small server-rendered surface asks me to rule on the handful of claims where
   my judgment would actually move the ranking. Reviewing every single claim makes me want to lie down and cry. This keeps me sane.
5. **Calibration.** My rulings become the corpus the system is trying to predict. The goal
   isn't "score jobs well." It's "predict what I'd conclude, and only interrupt me when it
   can't."

---

## The parts I think are interesting

### Nothing gets a score. Everything gets a distribution.

Every dimension resolves to a distribution, an opening is a Monte Carlo trace over 200,000
samples, and the queue sorts on the probability that trace clears a configured bar. Yeah, I've been bayes-pilled. I think in distributions and uncertainy a lot.

### Confidence widens the distribution. It never scales the value.

Every claim records two things that are never pre-blended: what it says (`Poor`, `Mixed`,
`Strong`, or genuinely undetermined) and who vouched for it (`unexamined` → `model_proposed`
→ `precedent_matched` → `ratified`). Provenance sets the *variance*. That sounds like a small distinction and it's the most important decisions that hold up the system. We're trying to narrow the universe of possibilities and as we are able to pile on more rigorous evidence, the system becomes more confident and less uncertain.

### The model decides. A deterministic loop acts.

There is exactly one LLM-shaped decision in the research loop: a planner returns a plan, and
it doesn't call anything. I thought that we were going to leverage an agent framework, but it turns out that the squishy judgement stuff is pretty narrow, but still important. I'm taking the best part of LLMs and the testability of deterministic loops and getting the best of both methods.

### The transcript is the state.

Every tool call—search, fetch, and the planner's own decisions—appends to a JSONL research
trace. When an interrupted pass resumes, the values it needs are derived from that transcript. Simpler surface and less opportunities for things to go sideways. Have I mentioned that I like immutable data structures? 

---

## How it was built

Vibe engineered, in the sense that I typed very few of these characters myself. But my hand is very much present in the background guiding the direction and steering when it goes off course. Work starts as a *scouting* document of findings, each one anchored to a
`file:line` or an architecture id, paired with a *bearing* of commitments that each cite the
finding they rest on. 

Inside a bearing the agent has full autonomy; outside it, none. To keep it on track, we have a small set of falsifiable tripwires. Any of those stops the work and hands me a choice with its
consequence spelled out. Cycles are small and test-first with the failing output pasted
before the implementation exists, which is what makes the whole thing reliable regardless of
which model is driving.

The discipline gates exist to keep agents honest so my review can be about something worth
reviewing. `uv run python scripts/check.py` runs tests, lint, formatting, strict typing,
and a handfull of things a linter structurally can't. The payoff is that I read diffs for structure and usability instead of walking the building checking which windows got broken.

`docs/architecture/` is the other half, a running decision record of the beams that are
harder to move and why they're there. Its index classifies ground rather than describing it:
**girders**, where a change is an escalation; **volatile**, where the architecture's only job
is to keep the thing cheap to move later; and everything else as open space, declared by
omission, because the default is autonomy and only the rails get enumerated. Decisions are
append-only and each names what was rejected and why, tagged `demonstrated` (reopening needs
new evidence, not new taste), `adopted`, or `provisional`. Some of the most useful entries
are records of things that didn't work.

---

## Running it

Python 3.14 and [uv](https://docs.astral.sh/uv/). You'll want a [Tavily](https://tavily.com)
key for search and extraction, plus one LLM provider key. Fireworks, OpenAI, and Anthropic
are interchangeable via config, and the default is picked for cost rather than capability.

```bash
cp .env.example .env   # then fill in the keys
```

Screen a posting by pasting the URL into the intake page once the server is running:

```bash
uv run uvicorn screen.api.app:app --port 8420
```

Then open http://localhost:8420/intake-queue and submit a job posting URL.
From there you can spend research turns, rule on the claims the system flags as worth your
attention, and watch the ranking move underneath you. Everything lands in `./data`, a SQLite
file plus the research traces.

To run the gates:

```bash
uv run python scripts/check.py
```

## License

AGPL-3.0-or-later. Copyright © 2026 Matthew Cox.

Use it, learn from it, adapt the ideas. If you run a modified version as a network service,
the AGPL asks you to publish your changes, which is the outcome I actually care about. If
those terms don't work for what you have in mind, get in touch and we'll sort something out.
I'd just like to know about it.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the [LICENSE](LICENSE) file for details.
