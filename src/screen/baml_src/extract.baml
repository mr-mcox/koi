// Extract typed assertions from one page-content chunk.
//
// The output schema matches `screen.types.Assertion` field-for-field.
// `target` must be one of the closed vocabulary slugs listed in the
// rubric_text argument; `fit` must be Poor, Mixed, or Strong.
// `citations` is always non-empty — every assertion must be grounded.
//
// The function receives `existing_assertions` so it can avoid
// duplicating claims already extracted in a prior pass.

class Citation {
  url string @description("The URL of the source page where this claim was found.")
  quote string @description("The verbatim span from the source that supports this claim. Must be present and non-empty.")
  host string @description("The domain serving the content, e.g. 'linkedin.com' or 'acme.com'.")
  source_provenance string @description("Whether this host is the originating source or an aggregator mirror, e.g. 'official', 'aggregator', 'news'.")
  independent bool @description("True if this citation is corroborating evidence from an independent source; false if it is the same underlying claim re-published.")
  source_date string? @description("ISO date (YYYY-MM-DD) when the claim was observed, if available. Null if unknown.")
}

class Assertion {
  target string @description("The rubric slug this claim pertains to. Must be one of the scoring dimension slugs, or 'non_scoring:obtainability'. See the rubric text for the complete closed vocabulary.")
  fit string @description("Poor, Mixed, or Strong — the claim's polarity in rubric vocabulary. Do not emit numeric scores.")
  provenance string @description("Always 'model_proposed' for assertions produced by this function.")
  chunk string @description("The verbatim span from the page content that grounded this claim. Must be non-empty.")
  citations Citation[] @description("One or more citations. Always non-empty. For a job posting the URL is the posting URL and the quote is the span supporting the claim.")
  created_at string @description("ISO 8601 UTC timestamp of extraction, e.g. '2026-08-26T12:00:00Z'.")
}

function ExtractAssertions(
  chunk: string,
  rubric_text: string,
  existing_assertions: string,
) -> Assertion[] {
  client Fireworks
  prompt #"
    You are a job-screener research assistant. Read the page content below
    and extract typed, source-cited assertions about the company or opening.

    ## Rubric
    {{ rubric_text }}

    ## Rules
    - Each assertion must have a `target` from the rubric's closed slug vocabulary
      (dimension slugs, or `non_scoring:obtainability`).
    - `fit` must be exactly one of: Poor, Mixed, Strong.
    - `provenance` must be `model_proposed`.
    - `chunk` must be a verbatim span copied from the page content below.
    - `citations` must be non-empty. Use the page URL as the citation URL
      and a verbatim span as the quote.
    - Do NOT emit numeric scores or confidence weights.
    - Do NOT duplicate claims already present in existing assertions.
    - Produce only claims that are directly supported by the text below.
      Do not infer or speculate.
    - Aim for 3–8 assertions per chunk. More than 10 is a sign of over-extraction.

    ## Existing assertions (do not duplicate)
    {{ existing_assertions }}

    ## Page content
    ```
    {{ chunk }}
    ```

    {{ ctx.output_format }}
  "#
}

// Smoke test: verify ExtractAssertions extracts at least one typed assertion
// from a realistic posting fixture.
//
// Fixture is the same anonymized Acme Health posting used in identify.baml.
// Run with `baml-cli test` (not `scripts/check.py`). Costs one model call.
test ExtractAssertions_AcmeHealthStaffPlatform {
  functions [ExtractAssertions]
  args {
    chunk #"
# Staff Platform Engineer
Acme Health

Posted 12 Days Ago · 3 Locations · In-Office or Remote · competitive · Senior level

Build and own the platform every engineer at Acme Health deploys on. We're a Series B company, well-funded, serving 200K users across the country. Our infrastructure runs on ECS/EKS, Terraform self-serve, autoscaling, and a Python monolith. We're hiring a Staff Platform Engineer to make infrastructure boring, scalable, and self-serve.

About Us

Acme Health is building a new scheduling system that providers run their practice on. The admin work — credentialing, claims, payment reconciliation — is automated end-to-end. We're a team of about 200 working across clinical operations, engineering, and platform. We've taken capital from Hypothetical Ventures and are growing the engineering team.

About the Role

You'll lead Platform Engineering with peer managers across Application and AI. You'll own cloud platform architecture, deployment blast-radius containment, autoscaling trustworthiness, cost attribution, and Terraform self-serve. Our mandate is to make every change safe from the start and build systems that get safer as they get faster.

About You

10+ years in platform or infrastructure engineering. Shipped cloud platforms at staff level. Comfortable with Python, AWS, ECS/EKS, Terraform, fast-moving teams.
    "#
    rubric_text #"
Scored dimensions: stretch (weight 3), peer (weight 2), trajectory (weight 2), mission (weight 2), agentic (weight 2), compensation (weight 2), domain (weight 1).
Additional dimensions: location (weight 6), internal_culture (weight 4), extractive_business (weight 4).
Non-scoring slug: non_scoring:obtainability.
Fit: Poor = the claim is negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
    existing_assertions "[]"
  }
  @@assert({{ this|length > 0 }})
  @@assert({{ this[0].chunk|length > 0 }})
  @@assert({{ this[0].fit in ["Poor", "Mixed", "Strong"] }})
  @@assert({{ this[0].citations|length > 0 }})
}
