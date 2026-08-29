"""Pydantic models for the job screener domain.
`extra="forbid"` on every model enforces Wall 1/2 (no scoring fields).
The closed `Target` Literal enforces Wall 3 (no unknown targets).
`tests/test_types.py` pins all three properties at the test level.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    created_at: Annotated[datetime, Field()]


class Opening(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(min_length=1)]
    company_id: Annotated[str, Field(min_length=1)]
    title: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    research_trace_id: Annotated[str, Field(min_length=1)]
    created_at: Annotated[datetime, Field()]


class IdentificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: Annotated[str, Field(min_length=1)]
    opening_title: Annotated[str, Field(min_length=1)]
    opening_notes: Annotated[str, Field(min_length=0)]


# ---------------------------------------------------------------------------
# Assertion and supporting types
# ---------------------------------------------------------------------------

# Scoring dimension slugs (domain-model.md §Scored dimensions)
_SCORING_TARGETS = [
    "stretch",
    "schematic",
    "peer",
    "trajectory",
    "mission",
    "agentic",
    "compensation",
    "domain",
]

# Constraint slugs (domain-model.md §Constraints)
_CONSTRAINT_TARGETS = [
    "location",
    "internal_culture",
    "extractive_business",
]

# Non-scoring targets carry the `non_scoring:` namespace prefix so the
# same word can never be confused with a scoring slug (Wall 3).
_NON_SCORING_TARGETS = [
    "non_scoring:obtainability",
]

# Wall 3: closed vocabulary; any value outside this set is rejected at
# validation time, not by scorer logic.
Target = Literal[
    "stretch",
    "schematic",
    "peer",
    "trajectory",
    "mission",
    "agentic",
    "compensation",
    "domain",
    "location",
    "internal_culture",
    "extractive_business",
    "non_scoring:obtainability",
]

# Fit values mirror the rubric's Poor / Mixed / Strong vocabulary.
# Stored as strings, not integers — unblended with confidence (D2).
Fit = Literal["Poor", "Mixed", "Strong"]

# Provenance tracks how an assertion came to exist.
# `model_proposed` is the initial state for all BAML-extracted assertions.
Provenance = Literal[
    "unexamined",
    "model_proposed",
    "precedent_matched",
    "ratified",
]


class Citation(BaseModel):
    """A single source that grounds a claim.

    `url` and `quote` are always required — the quote is the verbatim
    span from the source that supports the claim, making evidence
    ctrl-F-able (E1). `host` is the domain that served the content
    (e.g., `linkedin.com` vs `acme.com/careers`). `source_provenance`
    distinguishes whether the host is the originating source or an
    aggregator mirror. `independent` records whether this citation is
    corroborating evidence or the same underlying claim re-published;
    `source_date` captures when the claim was observed, if available.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: Annotated[str, Field(min_length=1)]
    quote: Annotated[str, Field(min_length=1)]
    host: Annotated[str, Field(min_length=1)]
    source_provenance: Annotated[str, Field(min_length=1)]
    independent: bool
    source_date: str | None = None


class Assertion(BaseModel):
    """One typed, source-cited claim about a company or opening.

    `target` is the rubric dimension, constraint slug, or non-scoring
    target the claim pertains to. `fit` is the claim's polarity in
    rubric vocabulary. `chunk` is the verbatim page span the extractor
    drew the claim from. `citations` is always non-empty — every
    assertion must be grounded.

    No scoring fields (Wall 1/2). `target` is a closed Literal (Wall 3).
    Assertions are append-only; this model is frozen (Wall 6 on the type).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(default_factory=lambda: str(uuid4()), min_length=1)]
    target: Target
    fit: Fit
    provenance: Provenance
    chunk: Annotated[str, Field(min_length=1)]
    citations: Annotated[list[Citation], Field(min_length=1)]
    created_at: Annotated[datetime, Field()]


class AssertionRuling(BaseModel):
    """An operator's confirm/override verdict on one `Assertion`.

    Sibling to `Assertion`, not a scoped union with a future `DimensionRuling` —
    assertion-level override ("was this claim right?") and dimension-level
    placement ("where does this dimension land?") are different author-intents
    with different payload shapes (domain-model.md, F25/F28). `fit` reuses the
    same closed rubric vocabulary as `Assertion.fit`; this type introduces no
    new vocabulary and stays a categorical confirm/override, not a continuous
    placement.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(default_factory=lambda: str(uuid4()), min_length=1)]
    assertion_id: Annotated[str, Field(min_length=1)]
    fit: Fit
    created_at: Annotated[datetime, Field()]
