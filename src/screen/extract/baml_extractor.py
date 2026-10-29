"""BAML adapter: bridges generated `baml_client` extraction results to the domain.

BAML only extracts assertions (`ExtractedAssertion`). Jev classifies
those extracted assertions into the final `screen.types.Assertion` shape, and anything
Jev confidently judges irrelevant to its target is dropped before persistence.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from screen.baml_client.sync_client import b
from screen.baml_client.types import Assertion as BAMLAssertion
from screen.extract.types import ExtractedAssertion, hydrate_assertion
from screen.types import Assertion
from screen.verdict.protocol import AssertionClassifier

# Threshold on Jev's `relevance_confidence` above which a "not relevant" verdict is trusted
# enough to drop the assertion rather than keep it at a wide distribution. Unmeasured —
# a placeholder until real-corpus confidence ranges are known (scouting F16).
RELEVANCE_DROP_THRESHOLD = 0.5


def _to_extracted_assertion(a: BAMLAssertion, now: datetime) -> ExtractedAssertion:
    """Validate the BAML output as the extraction-only domain shape."""
    dumped = a.model_dump()
    dumped["created_at"] = now
    return ExtractedAssertion.model_validate(dumped)


def classify_and_filter(
    extracted: list[ExtractedAssertion], classifier: AssertionClassifier
) -> list[Assertion]:
    """Classify each extracted assertion and drop anything Jev confidently judges
    irrelevant to its target, before it ever reaches storage."""

    def _classify_one(extracted_assertion: ExtractedAssertion) -> Assertion | None:
        classification = classifier.classify(extracted_assertion.chunk, extracted_assertion.target)
        if (
            not classification.is_relevant
            and classification.relevance_confidence >= RELEVANCE_DROP_THRESHOLD
        ):
            return None
        return hydrate_assertion(extracted_assertion, classification)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(_classify_one, extracted)

    return [r for r in results if r is not None]


class BAMLExtractor:
    """Satisfies `Extractor`. Calls `ExtractAssertions` via the BAML sync client,
    then runs Jev classification to hydrate the final assertion shape.
    """

    def __init__(self, classifier: AssertionClassifier) -> None:
        self._classifier = classifier

    def extract_assertions(
        self,
        chunk: str,
        rubric_text: str,
        existing: list[Assertion],
    ) -> list[Assertion]:
        existing_json = json.dumps([a.model_dump(mode="json") for a in existing], indent=None)
        now = datetime.now(UTC)
        raw: list[BAMLAssertion] = b.ExtractAssertions(
            chunk=chunk,
            rubric_text=rubric_text,
            existing_assertions=existing_json,
        )
        extracted = [_to_extracted_assertion(a, now) for a in raw]
        return classify_and_filter(extracted, self._classifier)
