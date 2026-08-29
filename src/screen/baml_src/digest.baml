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
    single scannable sentence (two only if the evidence genuinely needs it)
    summarizing what the evidence actually says.

    ## Rubric context
    {{ rubric_text }}

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

// Smoke test: verify DigestDimension produces prose without a Fit word.
// Run with `baml-cli test` (not `scripts/check.py`). Costs one model call.
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
  @@assert({{ this|length > 0 }})
}
