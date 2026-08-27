// Identify Company + Opening from a posting's page content.
//
// The default client is Fireworks (cheap, capable, 8b). The function's
// output fields map to `screen.types.IdentificationResult`; the
// generated Pydantic in `src/screen/baml_client/` should match that
// schema field-for-field, and the wrapper at
// `screen.intake.identify` coerces the generated model into the
// canonical one.

class IdentificationResult {
  company_name string @description("The legal or commonly-known company name. Should not include department or product name.")
  opening_title string @description("The title of the role as it would appear to applicants (e.g., 'Staff Engineer' or 'Applied AI Lead').")
  opening_notes string @description("Free-text summary the LLM uses to distinguish openings when more than one is in scope. Not persisted as a user-visible field at slice 2.")
}

function IdentifyOpening(page_content: string) -> IdentificationResult {
  client Fireworks
  prompt #"
    Read the following job posting and identify:

    1. The company that posted the opening.
    2. The title of the role.
    3. A short free-text note distinguishing this role from another role
       at the same company.

    Page content:
    ```
    {{ page_content }}
    ```

    {{ ctx.output_format }}
  "#
}

// Smoke-test: verify that IdentifyOpening extracts company name and
// role title correctly from a realistic-shaped posting.
//
// Fixture anonymized from a real posting (data/b7a254636963): company
// name → Acme Health, role → Staff Platform Engineer, recruiter
// boilerplate (funding, sector text, salary) → neutral variants. Real
// company names and figures do not appear here.
//
// Run with `baml-cli test` (not `scripts/check.py`). Costs one
// model call per execution. Substring assertions absorb spelling drift
// across model versions.
test IdentifyOpening_AcmeHealthStaffPlatform {
  functions [IdentifyOpening]
  args {
    page_content #"
# Staff Platform Engineer
Acme Health

Posted 12 Days Ago · 3 Locations · In-Office or Remote · competitive · Senior level

Build and own the platform every engineer at Acme Health deploys on. We're a Series B company, well-funded, serving 200K users across the country. Our infrastructure runs on ECS/EKS, Terraform self-serve, autoscaling, and a Python monolith. We're hiring a Staff Platform Engineer to make infrastructure boring, scalable, and self-serve.

About Us

Acme Health is building a new schedulingcare system that providers run their practice on. The admin work — credentialing, claims, payment reconciliation — is automated end-to-end. We're a team of about 200 working across clinical operations, engineering, and platform. We've taken capital from Hypothetical Ventures and are growing the engineering team.

About the Role

You'll lead Platform Engineering with peer managers across Application and AI. You'll own cloud platform architecture, deployment blast-radius containment, autoscaling trustworthiness, cost attribution, and Terraform self-serve. Our mandate is to make every change safe from the start and build systems that get safer as they get faster.

About You

10+ years in platform or infrastructure engineering. Shipped cloud platforms at staff level. Comfortable with Python, AWS, ECS/EKS, Terraform, fast-moving teams.
    "#
  }
  @@assert({{ "Acme Health" in this.company_name }})
  @@assert({{ "Staff" in this.opening_title }})
  @@assert({{ "Platform" in this.opening_title or "Engineer" in this.opening_title }})
  @@assert({{ this.opening_notes|length > 0 }})
}
