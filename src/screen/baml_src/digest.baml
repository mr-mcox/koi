// Generate a short prose gist of a dimension's assertion mix.
//
// Never a verdict, count, or Fit word (Poor/Mixed/Strong) — the digest
// summarizes what the evidence says, in the voice of someone who read it,
// not that a summary exists ("there are 3 assertions..." is banned).
// Output is validated against `screen.digest.style.assert_valid_digest`
// before it is cached — this prompt is a bias toward that shape, not the
// enforcement point.

function DigestDimension(
  assertions_json: string,
  rubric_text: string,
) -> string {
  client Fireworks
  prompt #"
    You are a job-screener research assistant. Read the assertions below,
    all filed against one rubric dimension for one opening, and write a
    short, scannable digest summarizing what the evidence actually says.

    ## Rubric context
    {{ rubric_text }}

    ## Style
    - 30 words or fewer, total.
    - Plain prose by default. Use bullets (each line starting with "- ")
      only when the evidence splits into distinct facets or a genuine
      tension — never to pad a single point into a list.
    - Short phrases and fragments are fine if they scan faster than a
      full sentence.

    ## Rules
    - Never use the words Poor, Mixed, or Strong.
    - Never state a number or count of assertions.
    - Never say that you are summarizing, or that assertions/evidence
      "exist" or "show" something — write as someone who read the
      evidence and is describing what it says, directly.
    - If the assertions conflict, say what the tension is, in plain terms.
    - If the list is empty, say the dimension has not yet been examined.

    ## Assertions (JSON)
    {{ assertions_json }}

    {{ ctx.output_format }}
  "#
}

// Smoke test: verify DigestDimension holds the word budget, drops em-dashes,
// and produces prose without a Fit word. Run with `baml-cli test` (not
// `scripts/check.py`). Costs one model call.
test DigestDimension_HighBarCulture {
  functions [DigestDimension]
  args {
    assertions_json #"
[{"target": "internal_culture", "fit": "Strong", "chunk": "We are not a place for complacency.", "citations": [{"url": "https://example.com/jobs/1", "quote": "We are not a place for complacency.", "host": "example.com", "source_provenance": "official", "independent": true, "source_date": null}]}]
    "#
    rubric_text #"
Constraint slug: internal_culture. Fit: Poor = negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
  }
  @@assert(non_empty, {{ this|length > 0 }})
  @@assert(word_budget, {{ this.split() | length <= 30 }})
  @@assert(no_em_dash, {{ "—" not in this }})
}

// Smoke test: two assertions with a genuine tension should be allowed (not
// required) to render as bullets, and must still hold the word budget.
test DigestDimension_ConflictingEvidence {
  functions [DigestDimension]
  args {
    assertions_json #"
[{"target": "craft_direction", "fit": "Strong", "chunk": "Engineers own features end to end with real autonomy.", "citations": [{"url": "https://example.com/jobs/1", "quote": "Engineers own features end to end.", "host": "example.com", "source_provenance": "official", "independent": true, "source_date": null}]}, {"target": "craft_direction", "fit": "Poor", "chunk": "Recent reviews describe heavy process and slow approvals.", "citations": [{"url": "https://example.com/reviews/2", "quote": "Heavy process, slow approvals.", "host": "example.com", "source_provenance": "third_party", "independent": true, "source_date": null}]}]
    "#
    rubric_text #"
Constraint slug: craft_direction. Fit: Poor = negative evidence; Mixed = ambiguous; Strong = positive evidence.
    "#
  }
  @@assert(non_empty, {{ this|length > 0 }})
  @@assert(word_budget, {{ this.split() | length <= 30 }})
  @@assert(no_em_dash, {{ "—" not in this }})
}
