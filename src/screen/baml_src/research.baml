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
  opening_id: string,
  company_name: string,
  opening_title: string,
  rubric_text: string,
  targets_covered: string,
  searches_used: int,
  search_budget: int,
  tokens_used: int,
  token_budget: int,
  last_context_text: string,
  coverage_summary: string,
) -> Action[] {
  client Fireworks
  prompt #"
    You are a research-pass planner for a job screener.

    ## Your job
    Decide what to do next in a research pass on a job opening.
    Return a list of actions. Available actions: `stop`, `fetch`, `search`.

    ## When to stop
    Stop when any of the following is true:
    - All rubric targets listed below have at least one assertion.
    - The search budget is exhausted (searches_used >= search_budget).
    - The token budget is exhausted (tokens_used >= token_budget).
    - There is nothing further to research with the available tools.

    ## When to fetch
    Fetch a specific URL when the last context revealed an outbound link worth
    following to gather more evidence for uncovered rubric targets.

    Prefer links that directly address a missing target (e.g. a compensation
    benchmark, an engineering blog post, a funding/trajectory page, a team page).
    Skip navigation links, home/contact/login pages, social media, and generic
    "about us" links — they rarely add scorable evidence. If the last context
    reveals only low-value links, issue a search instead of stopping.

    ## When to search
    Issue a search query when rubric targets remain uncovered and there is no
    specific URL worth fetching from the last context. A search opens new
    sourcing paths — use it to find compensation benchmarks, engineering culture
    pages, funding history, or other evidence for missing targets.

    Make the query specific: include the company name ({{ company_name }})
    and the missing target (e.g. "{{ company_name }} staff engineer
    compensation 2024", "{{ company_name }} engineering blog culture").
    Avoid queries already in prior_queries.

    ## State
    Company: {{ company_name }}
    Opening: {{ opening_title }} ({{ opening_id }})
    Rubric targets covered so far: {{ targets_covered }}
    Coverage summary: {{ coverage_summary }}
    Searches used: {{ searches_used }} / {{ search_budget }}
    Tokens used: {{ tokens_used }} / {{ token_budget }}
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

// Fixture: last fetch revealed one outbound link to a comp benchmarking page;
// coverage is incomplete → model should fetch the URL.
test DecidePlan_FetchesWhenContextRevealedUrl {
  functions [DecidePlan]
  args {
    opening_id "op-acme-staff-platform"
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch, peer"
    coverage_summary "stretch(1), peer(1)"
    searches_used 0
    search_budget 5
    tokens_used 1200
    token_budget 50000
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
    opening_id "op-acme-staff-platform"
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch"
    coverage_summary "stretch(1)"
    searches_used 0
    search_budget 5
    tokens_used 1200
    token_budget 50000
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch. Snippet: '...read our engineering blog at https://eng.acme.com and see compensation at https://levels.fyi/companies/acme and culture notes at https://glassdoor.com/acme ...'"
  }
  // Model must return exactly one action
  @@assert({{ this|length == 1 }})
  @@assert({{ this[0].tag == "fetch" }})
  @@assert({{ this[0].url|length > 0 }})
}

// Fixture: last fetch snippet contains multiple URLs, but only one is relevant
// to a coverage gap; model must ignore the navigation noise and fetch the
// relevant URL.
test DecidePlan_FetchesRelevantUrlAmongNoise {
  functions [DecidePlan]
  args {
    opening_id "op-acme-staff-platform"
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch, peer, trajectory, mission, agentic, domain"
    coverage_summary "stretch(1), peer(1), trajectory(1), mission(1), agentic(1), domain(1)"
    searches_used 0
    search_budget 5
    tokens_used 1200
    token_budget 50000
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch, peer, trajectory, mission, agentic, domain. Snippet: '...compensation details: https://example.com/contact-us, https://example.com/home, https://levels.fyi/companies/acme, https://example.com/login, ...'"
  }
  @@assert({{ this|length == 1 }})
  @@assert({{ this[0].tag == "fetch" }})
  @@assert({{ this[0].url == "https://levels.fyi/companies/acme" }})
}

// Fixture: only low-value navigation links are available, but there is a real
// coverage gap (compensation). Because no useful URL is revealed, model should
// stop rather than waste a fetch on a navigation page.
// Fixture: only low-value navigation links are available, but there is a real
// coverage gap (compensation). Because no useful URL is revealed, model should
// not fetch a navigation page — it may stop or search instead, both are fine.
test DecidePlan_AvoidsFetchWhenOnlyLowValueUrlsAvailable {
  functions [DecidePlan]
  args {
    opening_id "op-acme-staff-platform"
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch, peer, trajectory, mission, agentic, domain"
    coverage_summary "stretch(1), peer(1), trajectory(1), mission(1), agentic(1), domain(1)"
    searches_used 0
    search_budget 5
    tokens_used 1200
    token_budget 50000
    last_context_text "Last action: fetched https://example.com/jobs/42. Assertions added for targets: stretch, peer, trajectory, mission, agentic, domain. Snippet: 'Quick links: https://example.com/home | https://example.com/about | https://example.com/contact | https://example.com/login'"
  }
  @@assert({{ this|length == 1 }})
  @@assert({{ this[0].tag != "fetch" }})
}

// Fixture: last fetch was a hub page with no scorable content and no useful links;
// no coverage gaps can be addressed — model should stop.
test DecidePlan_StopsWhenNoUsefulUrlInContext {
  functions [DecidePlan]
  args {
    opening_id "op-acme-staff-platform"
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch, peer, trajectory, mission, agentic, compensation, domain"
    coverage_summary "stretch(1), peer(1), trajectory(1), mission(1), agentic(1), compensation(1), domain(1)"
    searches_used 0
    search_budget 5
    tokens_used 1200
    token_budget 50000
    last_context_text "Last action: fetched https://example.com/hub. Assertions added for targets: (none). Snippet: 'Navigation menu: Home | About | Contact'"
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag == "stop" }})
  @@assert({{ this[0].reason|length > 0 }})
}

// Fixture: search context with uncovered targets — model should fetch or search,
// not stop. This is the search-continuation smoke test.
test DecidePlan_SearchContextWithUncoveredTargets {
  functions [DecidePlan]
  args {
    opening_id "op-acme-staff-platform"
    company_name "Acme Corp"
    opening_title "Staff Software Engineer"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch, agentic"
    coverage_summary "stretch(2), agentic(1)"
    searches_used 1
    search_budget 5
    tokens_used 1800
    token_budget 50000
    last_context_text "Last action: search for 'Acme Corp staff engineer compensation 2024'. Results:\n1. Levels.fyi — https://levels.fyi/companies/acme\n   Staff engineer total comp at Acme ranges $380k–$450k TC.\n2. Glassdoor — https://glassdoor.com/acme-salaries\n   Engineers report strong salary but unclear equity.\n3. Blind — https://teamblind.com/acme\n   Recent posts on Acme comp and culture."
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag != "stop" }})
}

// Fixture: distinctive company name, real coverage gap, no useful URL in
// context — model must search, and the query it writes must be grounded in
// the actual company name rather than a generic recombination of the
// opening_id slug.
test DecidePlan_SearchQueryGroundedInCompanyName {
  functions [DecidePlan]
  args {
    opening_id "staff-software-engineer-backend-platform-28eb3f"
    company_name "Zylophonic"
    opening_title "Staff Software Engineer, Backend Platform"
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Constraint slugs: location, internal_culture, extractive_business.
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    targets_covered "stretch, agentic, domain"
    coverage_summary "stretch(2), agentic(1)"
    searches_used 0
    search_budget 5
    tokens_used 0
    token_budget 50000
    last_context_text ""
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].tag == "search" }})
  @@assert({{ "Zylophonic" in this[0].query }})
}
