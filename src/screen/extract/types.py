"""Intermediate extraction shapes for assertions.

These are the fields BAML is allowed to emit before Jev classification assigns fit
and confidence. The point of the split is to keep extraction and judgment separate
until the latter has run.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from screen.types import Assertion, Citation, Target
from screen.verdict.classification_protocol import AssertionClassification


class ExtractedAssertion(BaseModel):
    """An assertion before judgment: target, chunk, citations, created_at."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: Target
    chunk: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
    created_at: datetime


def hydrate_assertion(
    extracted: ExtractedAssertion, classification: AssertionClassification
) -> Assertion:
    """Attach Jev's fit judgment and confidence to an extracted assertion."""

    return Assertion(
        id=str(uuid4()),
        target=extracted.target,
        fit=classification.fit,
        provenance="model_proposed",
        chunk=extracted.chunk,
        citations=extracted.citations,
        created_at=extracted.created_at,
        confidence=classification.confidence,
    )
