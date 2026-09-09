"""Hand-written mappers between `screen.types` domain models and SQLite rows.

No ORM: `screen.types` is the one domain model;
a row is a plain `dict[str, object]` shaped to match the `companies`/
`openings`/`assertions` tables in `store/migrations/`. `sqlite3.Row` objects
convert to this shape via `dict(row)`.
"""

import json
from datetime import datetime

from screen.types import (
    Assertion,
    AssertionRuling,
    Citation,
    Company,
    DimensionDigest,
    DimensionRuling,
    Opening,
)


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
        "research_turns_budget": opening.research_turns_budget,
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
            "research_turns_budget": int(str(row["research_turns_budget"])),
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


def assertion_from_row(row: dict[str, object]) -> Assertion:
    citations = [Citation.model_validate(c) for c in json.loads(str(row["citations"]))]
    return Assertion.model_validate(
        {
            "id": str(row["id"]),
            "target": row["target"],
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


def dimension_digest_from_row(row: dict[str, object]) -> DimensionDigest:
    return DimensionDigest.model_validate(
        {
            "opening_id": str(row["opening_id"]),
            "target": row["target"],
            "digest": str(row["digest"]),
            "assertion_count": int(str(row["assertion_count"])),
            "computed_at": datetime.fromisoformat(str(row["computed_at"])),
        }
    )


def dimension_ruling_to_row(ruling: DimensionRuling) -> dict[str, object]:
    return {
        "id": ruling.id,
        "opening_id": ruling.opening_id,
        "target": ruling.target,
        "mean": ruling.mean,
        "settledness": ruling.settledness,
        "created_at": ruling.created_at.isoformat(),
        "covered_assertion_ids": json.dumps(ruling.covered_assertion_ids),
    }


def dimension_ruling_from_row(row: dict[str, object]) -> DimensionRuling:
    return DimensionRuling.model_validate(
        {
            "id": str(row["id"]),
            "opening_id": str(row["opening_id"]),
            "target": row["target"],
            "mean": float(str(row["mean"])),
            "settledness": float(str(row["settledness"])),
            "created_at": datetime.fromisoformat(str(row["created_at"])),
            "covered_assertion_ids": json.loads(str(row.get("covered_assertion_ids", "[]"))),
        }
    )
