"""Hand-written mappers between `screen.types` domain models and SQLite rows.

No ORM: `screen.types` is the one domain model;
a row is a plain `dict[str, object]` shaped to match the `companies`/
`openings`/`assertions` tables in `store/migrations/`. `sqlite3.Row` objects
convert to this shape via `dict(row)`.

Read-path mappers silently drop rows whose `target` is no longer in the
closed rubric vocabulary, warning once per row. This lets the operator's
live `data/live/` DB outlive rubric revisions without requiring a migration
before the app can render; retired evidence becomes unexamined, not
reinterpreted under a renamed dimension.
"""

import json
import warnings
from datetime import datetime
from typing import Any, cast, get_args

from screen.types import (
    Assertion,
    AssertionRuling,
    Citation,
    Company,
    Comparison,
    DimensionDigest,
    IntakeQueueItem,
    Opening,
    Target,
)

_VALID_TARGETS: frozenset[str] = frozenset(get_args(Target))


def _valid_target_or_warn(value: object) -> str | None:
    """Return the target slug if it is current; otherwise warn and return None.

    Dropping retired targets at the read boundary avoids crashes when an
    existing DB contains assertions for a renamed or removed dimension. This
    is a tolerance seam, not a validation rule — new writes still go through the
    strict `Target` Literal in `screen.types`.
    """
    slug = str(value)
    if slug in _VALID_TARGETS:
        return slug
    warnings.warn(
        f"Dropping stored row with retired/unknown target {slug!r} — "
        "not in current rubric; re-fetch if the dimension still matters.",
        UserWarning,
        stacklevel=3,
    )
    return None


def company_to_row(company: Company) -> dict[str, object]:
    return {
        "id": company.id,
        "name": company.name,
        "created_at": company.created_at.isoformat(),
    }


def company_from_row(row: dict[str, object]) -> Company:
    return Company(
        id=str(row["id"]),
        name=str(row["name"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def opening_to_row(opening: Opening) -> dict[str, object]:
    return {
        "id": opening.id,
        "company_id": opening.company_id,
        "title": opening.title,
        "url": opening.url,
        "research_trace_id": opening.research_trace_id,
        "created_at": opening.created_at.isoformat(),
        "stage": opening.stage,
    }


def opening_from_row(row: dict[str, object]) -> Opening:
    return Opening.model_validate(
        {
            "id": str(row["id"]),
            "company_id": str(row["company_id"]),
            "title": str(row["title"]),
            "url": str(row["url"]),
            "research_trace_id": str(row["research_trace_id"]),
            "created_at": datetime.fromisoformat(str(row["created_at"])),
            "stage": row.get("stage", "screening"),
        }
    )


def assertion_to_row(assertion: Assertion, *, opening_id: str) -> dict[str, object]:
    return {
        "id": assertion.id,
        "opening_id": opening_id,
        "target": assertion.target,
        "fit": assertion.fit,
        "provenance": assertion.provenance,
        "chunk": assertion.chunk,
        "citations": json.dumps([c.model_dump(mode="json") for c in assertion.citations]),
        "created_at": assertion.created_at.isoformat(),
    }


def assertion_from_row(row: dict[str, object]) -> Assertion | None:
    citations = [Citation.model_validate(c) for c in json.loads(str(row["citations"]))]
    target = _valid_target_or_warn(row["target"])
    if target is None:
        return None
    return Assertion.model_validate(
        {
            "id": str(row["id"]),
            "target": target,
            "fit": row["fit"],
            "provenance": row["provenance"],
            "chunk": str(row["chunk"]),
            "citations": citations,
            "created_at": datetime.fromisoformat(str(row["created_at"])),
        }
    )


def assertion_ruling_to_row(ruling: AssertionRuling) -> dict[str, object]:
    return {
        "id": ruling.id,
        "assertion_id": ruling.assertion_id,
        "fit": ruling.fit,
        "created_at": ruling.created_at.isoformat(),
    }


def assertion_ruling_from_row(row: dict[str, object]) -> AssertionRuling:
    return AssertionRuling.model_validate(
        {
            "id": str(row["id"]),
            "assertion_id": str(row["assertion_id"]),
            "fit": row["fit"],
            "created_at": datetime.fromisoformat(str(row["created_at"])),
        }
    )


def dimension_digest_to_row(digest: DimensionDigest) -> dict[str, object]:
    return {
        "opening_id": digest.opening_id,
        "target": digest.target,
        "digest": digest.digest,
        "assertion_count": digest.assertion_count,
        "computed_at": digest.computed_at.isoformat(),
    }


def dimension_digest_from_row(row: dict[str, object]) -> DimensionDigest | None:
    target = _valid_target_or_warn(row["target"])
    if target is None:
        return None
    return DimensionDigest.model_validate(
        {
            "opening_id": str(row["opening_id"]),
            "target": target,
            "digest": str(row["digest"]),
            "assertion_count": int(str(row["assertion_count"])),
            "computed_at": datetime.fromisoformat(str(row["computed_at"])),
        }
    )


def comparison_to_row(comparison: Comparison) -> dict[str, object]:
    return {
        "id": comparison.id,
        "opening_a_id": comparison.opening_a_id,
        "opening_b_id": comparison.opening_b_id,
        "target": comparison.target,
        "outcome": comparison.outcome,
        "predicted_a_beats_b": comparison.predicted_a_beats_b,
        "opening_a_digest_version": comparison.opening_a_digest_version,
        "opening_b_digest_version": comparison.opening_b_digest_version,
        "created_at": comparison.created_at.isoformat(),
    }


def comparison_from_row(row: dict[str, object]) -> Comparison | None:
    target = _valid_target_or_warn(row["target"])
    if target is None:
        return None
    return Comparison.model_validate(
        {
            "id": str(row["id"]),
            "opening_a_id": str(row["opening_a_id"]),
            "opening_b_id": str(row["opening_b_id"]),
            "target": target,
            "outcome": row["outcome"],
            "predicted_a_beats_b": float(cast(Any, row["predicted_a_beats_b"])),
            "opening_a_digest_version": row["opening_a_digest_version"],
            "opening_b_digest_version": row["opening_b_digest_version"],
            "created_at": datetime.fromisoformat(str(row["created_at"])),
        }
    )


def intake_queue_item_to_row(item: IntakeQueueItem) -> dict[str, object]:
    return {
        "id": item.id,
        "url": item.url,
        "status": item.status,
        "error": item.error,
        "created_at": item.created_at.isoformat(),
    }


def intake_queue_item_from_row(row: dict[str, object]) -> IntakeQueueItem:
    return IntakeQueueItem.model_validate(
        {
            "id": str(row["id"]),
            "url": str(row["url"]),
            "status": row["status"],
            "error": row["error"],
            "created_at": datetime.fromisoformat(str(row["created_at"])),
        }
    )
