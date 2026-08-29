"""Hand-written mappers between `screen.types` domain models and SQLite rows.

No ORM (score-persistence bearing): `screen.types` is the one domain model;
a row is a plain `dict[str, object]` shaped to match the `companies`/
`openings`/`assertions` tables in `store/migrations/`. `sqlite3.Row` objects
convert to this shape via `dict(row)`.
"""

import json
from datetime import datetime

from screen.types import Assertion, Citation, Company, DimensionDigest, Opening


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
    }


def opening_from_row(row: dict[str, object]) -> Opening:
    return Opening(
        id=str(row["id"]),
        company_id=str(row["company_id"]),
        title=str(row["title"]),
        url=str(row["url"]),
        research_trace_id=str(row["research_trace_id"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
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
