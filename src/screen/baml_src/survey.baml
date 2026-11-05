// Survey — the Surveyor's call: given everything known about one opening and
// how research has gone on it so far, pick the one rubric dimension worth
// investigating this pass and frame a specific research question for it.
//
// Shape 1 invariant (decisions.md E9): this call only reads state and
// proposes a dimension and a question; it never calls Tavily and never
// mutates state. The dispatcher decides when it runs (once per pass, before
// the first Navigate call) and validates the answer against the live rubric
// vocabulary — a dimension outside it fails the pass loudly rather than
// being silently remapped.
//
// Framing: hypothesis-first (chosen 2026-11-04 over search-ready-question and
// gap-description after a live multi-turn comparison — scouting F45, F49).
// `question` carries a falsifiable claim, not a restated question: measured
// against the other two framings, this produced the most genuine per-pass
// evidence diversity (distinct pages, distinct sites, named specifics) rather
// than re-querying the same target or fixating on one repeated guess.

class ResearchQuestion {
  dimension string @description("Exactly one dimension slug, copied verbatim from the list given.")
  question string @description("A specific, falsifiable hypothesis for that dimension — a claim you expect evidence to confirm or refute, with reasoning — not a restatement of its name and not a search query.")
}

function Survey(
  company_name: string,
  opening_title: string,
  rubric_text: string,
  dimensions: string,
  yield_summary: string,
  query_assertion_history: string,
) -> ResearchQuestion {
  client Fireworks
  prompt #"
    You are surveying a job opening to decide where research effort is most
    likely to pay off this pass.

    ## Your job
    Form a hypothesis about where there is real opportunity to learn
    something that would change this opening's standing — a specific,
    falsifiable claim about what you expect to find and why, grounded in one
    rubric dimension. This is not a search query: it is the thing you are
    trying to confirm or refute.

    ## Available dimensions
    {{ dimensions }}

    ## Rubric
    {{ rubric_text }}

    ## How research has gone on this opening so far
    {{ yield_summary }}

    ## What's already known, per dimension
    {{ query_assertion_history }}

    ## State
    Company: {{ company_name }}
    Opening: {{ opening_title }}

    Favor a dimension that is unexamined or has stalled elsewhere over one
    already well covered. Return exactly one dimension, chosen verbatim from
    the list above, and a hypothesis: a specific claim you expect evidence to
    confirm or refute, with your reasoning for why it's the most promising
    unknown right now.

    {{ ctx.output_format }}
  "#
}

// Smoke test — TDD harness for the Survey prompt.
// Run with: uv run baml-cli test --from baml_src -i "Survey::"
// NOT included in scripts/check.py (costs one model call per run).

// Fixture: one dimension has no assertions at all, the others are covered —
// model should pick the unexamined one.
test Survey_PicksUnexaminedDimension {
  functions [Survey]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: craft_direction (weight 3), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    dimensions "craft_direction, trajectory, mission, agentic, compensation, domain, location, internal_culture"
    yield_summary "craft_direction: 3 assertions filed. trajectory: 2 assertions filed. mission: 1 assertion filed. agentic: 2 assertions filed. compensation: 2 assertions filed. domain: 1 assertion filed. location: 1 assertion filed. internal_culture: unexamined — no prior research."
    query_assertion_history "(none yet for internal_culture)"
  }
  @@assert({{ this.dimension == "internal_culture" }})
  @@assert({{ this.question|length > 0 }})
}
