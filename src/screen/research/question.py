"""ResearchQuestion — the Surveyor's output: one rubric dimension worth
investigating this pass, framed as a specific question. `dimension` is `str`,
not `Target`: validating it against the live rubric vocabulary is the
dispatcher's job (it decides what happens on a bad answer), not a parse-time
concern of this type.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Annotated[str, Field(min_length=1)]
    question: Annotated[str, Field(min_length=1)]


# Placeholder Survey input, shared by `BAMLSurveyor` (what it actually sends)
# and the dispatcher (what it records as the audit snapshot) so the two can't
# drift apart. The real renderers (pool-wide/per-opening yield rates, the
# citation-URL-to-search join) are follow-up cycles (scouting F15, F23-F26,
# F32, F34) — this steel-threads the Survey prompt's shape first.
NOT_YET_AVAILABLE = (
    "(not yet available — yield-rate and query-history rendering land in a follow-up cycle)"
)
