// DecidePlan — the one LLM-shaped decision in the research dispatch pass.
//
// Shape 1 invariant: BAML generates the plan; the hand-written
// dispatcher owns every tool call and all state mutation.
//
// Returns a list of actions. StopAction and FetchAction are the supported
// tags in this slice. The output schema is a tagged union; the dispatcher
// matches on `tag`.
//
// The prompt body does not restate the output schema in prose —
// ctx.output_format handles it (same fix as IdentifyOpening in slice 2).

class StopAction {
  tag string @description("Always 'stop'.")
  reason string @description("One sentence: why the pass is stopping. Must be non-empty.")
}

class FetchAction {
  tag string @description("Always 'fetch'.")
  url string @description("The URL to fetch. Must be non-empty.")
}

class SearchAction {
  tag string @description("Always 'search'.")
  query string @description("The search query to issue. Must be non-empty.")
}

// Closed union for this slice.
type Action = StopAction | FetchAction | SearchAction

function DecidePlan(
  company_name: string,
  opening_title: string,
  rubric_text: string,
  primary_target: string,
  last_context_text: string,
  prior_queries: string,
) -> Action[] {
  client Fireworks
  prompt #"
    You are a research-pass planner for a job screener.

    ## Your job
    Decide what to do next in a research pass on a job opening.
    Return a list of actions. Available actions: `stop`, `fetch`, `search`.

    ## When to stop
    Return `stop` only when the last action was a `fetch` that added
    assertions for the primary target, and the fetched page has no
    unexplored relevant links left to follow for the primary target.

    Do not stop because the turn budget is low or exhausted — a separate
    process ends the pass when the budget runs out; you never need to count
    turns. Do not stop just because a search returned no immediately
    fetchable URL — issue a different search instead. Do not stop because a
    fetch added no assertions — that source was a dead end, try another one.

    ## When to fetch
    Fetch a specific URL when the last context revealed an outbound link worth
    following to gather more evidence for the primary target.

    Prefer links that directly address the primary target. Skip navigation
    links, home/contact/login pages, social media, and generic "about us" links
    — they rarely add scorable evidence. If the last context reveals only
    low-value links, issue a search instead. If the last context reveals a
    link that is relevant to the primary target but the page itself is likely
    a hub, you may fetch another link from that page in a subsequent turn.

    ## When to search
    Issue a search query when there is no specific URL worth fetching from the
    last context for the primary target. A search opens new sourcing paths — use
    it to find evidence for the primary target (e.g. compensation benchmarks,
    engineering culture pages, funding history, team pages).

    Make the query specific: include the company name ({{ company_name }}) and
    the primary target (e.g. "{{ company_name }} staff engineer compensation
    2024", "{{ company_name }} engineering blog culture"). Avoid repeating a
    query already in prior queries below.

    ## State
    Company: {{ company_name }}
    Opening: {{ opening_title }}
    Primary target this turn: {{ primary_target }}
    Prior queries: {{ prior_queries }}
    {% if last_context_text %}
    Last action result: {{ last_context_text }}
    {% endif %}

    ## Rubric
    {{ rubric_text }}

    ## Available actions
    - stop: end the pass and write the summary
    - fetch: retrieve a specific URL for more evidence
    - search: issue a web search query to find new sources

    Return exactly one action.

    {{ ctx.output_format }}
  "#
}

// Smoke test — TDD harness for the DecidePlan prompt.
// Run with: uv run baml-cli test --from baml_src -i "DecidePlan::"
// NOT included in scripts/check.py (costs one model call per run).

// Fixture: last fetch revealed one outbound link to a comp benchmarking page
// for the primary target — model should fetch the URL.
test DecidePlan_FetchesWhenContextRevealedUrl {
  functions [DecidePlan]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "(none)"
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch, peer. Snippet: '...see compensation benchmarks at https://levels.fyi/companies/acme ...'"
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag == "fetch" }})
  @@assert({{ this[0].url|length > 0 }})
}

// Fixture: last fetch snippet contains multiple candidate outbound links;
// model must pick exactly one fetch action (not stop, not multiple).
test DecidePlan_FetchesOneWhenMultipleUrlsAvailable {
  functions [DecidePlan]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "(none)"
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch. Snippet: '...read our engineering blog at https://eng.acme.com and see compensation at https://levels.fyi/companies/acme and culture notes at https://glassdoor.com/acme ...'"
  }
  // Model must return exactly one action
  @@assert({{ this|length == 1 }})
  @@assert({{ this[0].tag == "fetch" }})
  @@assert({{ this[0].url|length > 0 }})
}

// Fixture: last fetch snippet contains multiple URLs, but only one is relevant
// to the primary target; model must ignore the navigation noise and fetch the
// relevant URL.
test DecidePlan_FetchesRelevantUrlAmongNoise {
  functions [DecidePlan]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "(none)"
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch, peer, trajectory, mission, agentic, domain. Snippet: '...compensation details: https://example.com/contact-us, https://example.com/home, https://levels.fyi/companies/acme, https://example.com/login, ...'"
  }
  @@assert({{ this|length == 1 }})
  @@assert({{ this[0].tag == "fetch" }})
  @@assert({{ this[0].url == "https://levels.fyi/companies/acme" }})
}

// Fixture: only low-value navigation links are available for the primary
// target. Model should not fetch a navigation page — it may search or stop,
// both are fine, but never fetch junk.
test DecidePlan_AvoidsFetchWhenOnlyLowValueUrlsAvailable {
  functions [DecidePlan]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "Acme Corp compensation 2024"
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch, peer, trajectory, mission, agentic, domain. Snippet: 'Quick links: https://example.com/home | https://example.com/about | https://example.com/contact | https://example.com/login'"
  }
  @@assert({{ this|length == 1 }})
  @@assert({{ this[0].tag != "fetch" }})
}

// Fixture: search context with a promising primary-target hit — model should
// fetch or search, not stop. This is the search-continuation smoke test.
test DecidePlan_SearchContextWithUncoveredTarget {
  functions [DecidePlan]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "Acme Corp staff engineer compensation 2024"
    last_context_text "Last action: search for 'Acme Corp staff engineer compensation 2024'. Results:\n1. Levels.fyi — https://levels.fyi/companies/acme\n   Staff engineer total comp at Acme ranges $380k–$450k TC.\n2. Glassdoor — https://glassdoor.com/acme-salaries\n   Engineers report strong salary but unclear equity.\n3. Blind — https://teamblind.com/acme\n   Recent posts on Acme comp and culture."
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag != "stop" }})
}

// Fixture: last fetch was productive for the primary target and left no
// further relevant links — model should stop, per the narrow escape valve.
test DecidePlan_StopsWhenPrimaryTargetLeadIsMinedOut {
  functions [DecidePlan]
  args {
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "Acme Corp staff engineer compensation 2024"
    last_context_text "Last action: fetched https://levels.fyi/companies/acme. Assertions added for targets: compensation. Snippet: 'Staff engineer total comp at Acme ranges $380k-$450k TC. No further breakdown available. Page has no other outbound links.'"
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag == "stop" }})
  @@assert({{ this[0].reason|length > 0 }})
}

// Fixture: distinctive company name, no useful URL in context — model must
// search, and the query it writes must be grounded in the actual company
// name rather than a generic recombination of the opening title.
test DecidePlan_SearchQueryGroundedInCompanyName {
  functions [DecidePlan]
  args {
    company_name "Zylophonic"
    opening_title "Staff Software Engineer, Backend Platform"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    primary_target "compensation"
    prior_queries "(none)"
    last_context_text ""
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag == "search" }})
  @@assert({{ "Zylophonic" in this[0].query }})
}
