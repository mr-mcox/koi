"""Pydantic models for the job screener domain.
Bare ids below: `E*`/`S*` are `docs/architecture/decisions.md`,
`D*` are `docs/architecture/prototype-decisions.md`.
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
    research_turns_budget: Annotated[int, Field(ge=0)]
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
    with different payload shapes (domain-model.md §Ruling). `fit` reuses the
    same closed rubric vocabulary as `Assertion.fit`; this type introduces no
    new vocabulary and stays a categorical confirm/override, not a continuous
    placement.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(default_factory=lambda: str(uuid4()), min_length=1)]
    assertion_id: Annotated[str, Field(min_length=1)]
    fit: Fit
    created_at: Annotated[datetime, Field()]


class DimensionRuling(BaseModel):
    """The operator's own continuous placement for one dimension/opening: "given
    everything, where am I on this?" (domain-model.md §Ruling) — a non-arithmetic
    squish over the assertions and rulings underneath, not a formula computed off
    them. Sibling to `AssertionRuling`, not a shared type with a scope field:
    assertion-level rating is a categorical confirm/override, this is a continuous
    placement, and the two are different author-intents with different payload
    shapes.

    `mean` is the operator's stated fit, `[-1, 1]`, same scale `Assertion.fit`
    maps onto (`FIT_VALUES`). `settledness` is stated *conviction*, `[0, 1]` —
    0 is a loose opinion, 1 is the operator's strongest stated confidence, which
    still carries some spread (the operator may be noisy; the system may not
    manufacture a point estimate). The Scorer derives `half_width` from
    `settledness` via configured bounds (`hw_max`/`hw_min` in `scoring.yaml`),
    not stored here — this type carries only what the operator actually stated.

    Pins are not revertable: no delete path exists; resubmission upserts by
    `(opening_id, target)`, same pattern as `AssertionRuling`'s re-rating.

    `covered_assertion_ids` snapshots the target's assertion ids at ruling time
    (review-ux/dimension-ruling-drift bearing) — the exact partition between the
    evidence the operator ruled on and anything filed after. Defaults to `[]` for
    rulings predating this field; the drift backfill migration populates it for
    existing rows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(default_factory=lambda: str(uuid4()), min_length=1)]
    opening_id: Annotated[str, Field(min_length=1)]
    target: Target
    mean: Annotated[float, Field(ge=-1.0, le=1.0)]
    settledness: Annotated[float, Field(ge=0.0, le=1.0)]
    created_at: Annotated[datetime, Field()]
    covered_assertion_ids: Annotated[list[str], Field(default_factory=list)]


class DimensionDigest(BaseModel):
    """Cached prose gist of a dimension's assertion mix for one opening.

    Never a verdict, count, or Fit word (S7 · The rollup is mechanical; the model
    never renders verdicts).
    `assertion_count` is the staleness key: assertions are append-only (Wall 6),
    so a monotonic count comparison against the target's current assertion
    count is exact and sufficient to detect a stale digest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_id: Annotated[str, Field(min_length=1)]
    target: Target
    digest: Annotated[str, Field(min_length=1)]
    assertion_count: Annotated[int, Field(ge=0)]
    computed_at: Annotated[datetime, Field()]
