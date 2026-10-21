// Propose one rubric edit for recalibration.
//
// Returns theory, expected effect, and only the rubric fields being changed.
// Omitted fields are rehydrated from the current draft by the caller, so an
// unedited field round-trips verbatim. The caller renders the draft into rubric
// text and never sends the theory or expected effect back into Jev.

class RecalibrationProposal {
  theory string @description("One sentence: the pattern this edit is intended to fix.")
  expected_effect string @description("What measurable change you expect and in which direction, e.g. 'fewer wrong+sure on expected-tie pairs'.")
  definition string? @description("Full replacement definition text. Omit entirely if you are not changing it.")
  fit_anchor_poor string? @description("Full replacement Poor fit anchor. Omit entirely if you are not changing it.")
  fit_anchor_mixed string? @description("Full replacement Mixed fit anchor. Omit entirely if you are not changing it.")
  fit_anchor_strong string? @description("Full replacement Strong fit anchor. Omit entirely if you are not changing it.")
  look_for string? @description("Full replacement Look for text. Omit entirely if you are not changing it.")
}

function ProposeRubricEdit(
  current_rubric_text: string,
  current_cases_text: string,
  history_text: string,
) -> RecalibrationProposal {
  client AnthropicSonnet
  prompt #"
    You are editing one scoring dimension in a job-screener rubric.

    Your job:
    - Propose a small rubric edit that could improve agreement with operator rulings.
    - Return a structured record with:
      theory: one sentence explaining the pattern you think the edit addresses.
      expected_effect: what you expect to move and in which direction.
      definition / fit anchors / look_for: ONLY the fields you are changing.

    Hard rules:
    - Do not mention your theory inside the rubric text fields.
    - Omit any rubric field you are not changing. Do not echo it back unchanged —
      an omitted field is carried over verbatim for you.
    - For a field you do change, give its complete replacement text, not a diff.
    - Keep the edit as small as possible: prefer changing one field.
    - If you believe there is no wording defect, omit every rubric field and say so in theory.
    - Never include salary figures or other private values.
    - Use the examples and history to target the edit; do not repeat held-out results.

    ## Current rubric text
    {{ current_rubric_text }}

    ## Current cases
    {{ current_cases_text }}

    ## Prior rounds
    {{ history_text }}

    {{ ctx.output_format }}
  "#
}
