// Propose one rubric edit for recalibration.
//
// Returns theory, expected effect, and only the rubric fields being changed.
// Null fields are rehydrated from the current draft by the caller, so an
// unedited field round-trips verbatim. The caller renders the draft into rubric
// text and never sends the theory or expected effect back into Jev.

class RecalibrationProposal {
  theory string @description("One sentence: the pattern in the cases this edit targets. If you find no wording defect, say so here and leave every rubric field null.")
  expected_effect string @description("What measurable change you expect and in which direction, e.g. 'fewer wrong+sure on expected-tie pairs'.")
  definition string? @description("New definition value, or null if unchanged.")
  fit_anchor_poor string? @description("New fit_anchor_poor value, or null if unchanged.")
  fit_anchor_mixed string? @description("New fit_anchor_mixed value, or null if unchanged.")
  fit_anchor_strong string? @description("New fit_anchor_strong value, or null if unchanged.")
  look_for string? @description("New look_for value, or null if unchanged.")
}

function ProposeRubricEdit(
  current_rubric_text: string,
  current_cases_text: string,
  history_text: string,
  scoring_rule_text: string,
) -> RecalibrationProposal {
  client AnthropicSonnet
  prompt #"
    You are tuning one scoring dimension of a job-screener rubric so that a
    judge model ("jev") agrees more often with the operator.

    How the rubric is used: jev reads only the rubric text below and two
    evidence digests (A and B), then predicts which one fits this dimension
    better, or "tie". It never sees these cases, your theory, or prior rounds.

    How to read each case:
    - expected: the operator's ruling (a, b, or tie). This is ground truth.
    - jev: what jev predicted under the current rubric.
    - sure: True means jev would have committed without asking the operator.
    - conf: jev's confidence in its own prediction, 0-1.
    - p_ruling: the probability jev put on the operator's ruling, 0-1.

    How your edit is judged:
    {{ scoring_rule_text }}

    What to do:
    1. Find the group of cases where a shared wording problem costs the most
       under the rules above, and check it against the agreements so your edit
       doesn't break them.
    2. Make the smallest wording change that would lead jev to the operator's
       answer for that group. Prefer changing a single field.

    Rubric text requirements:
    - Each field you return is the complete new value for that field, written as a standalone criterion without references to these cases, pairs, rounds, or the reason for the change.
    - ALL_CAPS names such as SCREEN_COMPENSATION_BASELINE are placeholders filled with a private value when jev runs; keep every placeholder exactly as written.
    - No salary figures or other private values.

    ## Current rubric
    {{ current_rubric_text }}

    ## Current cases
    {{ current_cases_text }}

    ## Prior rounds
    {{ history_text }}

    {{ ctx.output_format }}
  "#
}
