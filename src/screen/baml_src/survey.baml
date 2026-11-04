// Survey — the Surveyor's call: given everything known about one opening and
// how research has gone on it so far, pick the one rubric dimension worth
// investigating this pass and frame a specific question for it.
//
// Shape 1 invariant (decisions.md E9): this call only reads state and
// proposes a dimension and a question; it never calls Tavily and never
// mutates state. The dispatcher decides when it runs (once per pass, before
// the first DecidePlan) and validates the answer against the live rubric
// vocabulary — a dimension outside it fails the pass loudly rather than
// being silently remapped.

class ResearchQuestion {
  dimension string @description("Exactly one dimension slug, copied verbatim from the list given.")
  question string @description("A specific, answerable research question for that dimension — not a restatement of its name.")
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
    You are surveying a job opening to decide what to research next.

    ## Your job
    Pick exactly one rubric dimension worth investigating this pass, and
    frame a specific research question for it — not just the dimension's
    name, but what you actually want to find out and why it would move this
    opening's standing.

    ## Available dimensions
    {{ dimensions }}

    ## Rubric
    {{ rubric_text }}

    ## How research has gone on this opening so far
    {{ yield_summary }}

    ## Past queries and what they found
    {{ query_assertion_history }}

    ## State
    Company: {{ company_name }}
    Opening: {{ opening_title }}

    Favor a dimension that is unexamined or has stalled elsewhere over one
    already well covered. Return exactly one dimension, chosen verbatim from
    the list above, and a question specific enough that a web search query
    could be built from it directly.

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
