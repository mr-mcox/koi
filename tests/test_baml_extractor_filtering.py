"""Tests for `classify_and_filter`: the Jev classification + relevance-drop pass.

Exercises the pure function directly with a fake classifier, so no BAML or
TypeSafe API call is involved — `BAMLExtractor` itself stays exempt per the
bearing (it wraps a paid API), but the filtering logic it delegates to is
test-first.
"""

from datetime import UTC, datetime

from screen.extract.baml_extractor import classify_and_filter
from screen.extract.types import ExtractedAssertion
from screen.types import Citation
from screen.verdict.classification_protocol import AssertionClassification


def _citation(**overrides: object) -> Citation:
    base = {
        "url": "https://example.com/jobs/42",
        "quote": "We use ECS/EKS and Terraform.",
        "host": "example.com",
        "source_provenance": "official",
        "independent": True,
        "source_date": None,
    }
    base.update(overrides)
    return Citation.model_validate(base)


def _extracted(**overrides: object) -> ExtractedAssertion:
    base: dict[object, object] = {
        "target": "craft_direction",
        "chunk": "Staff Platform Engineer, 10+ years required.",
        "citations": [_citation()],
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return ExtractedAssertion.model_validate(base)


class _FakeClassifier:
    """Returns canned classifications in order, matched to input by chunk text."""

    def __init__(self, by_chunk: dict[str, AssertionClassification]) -> None:
        self._by_chunk = by_chunk
        self.calls: list[tuple[str, str]] = []

    def classify(self, chunk: str, target: str) -> AssertionClassification:
        self.calls.append((chunk, target))
        return self._by_chunk[chunk]


def test_confidently_irrelevant_assertion_is_dropped() -> None:
    """A generic 'United States' location extraction, confidently judged irrelevant,
    never becomes a persisted Assertion."""
    irrelevant = _extracted(target="domain", chunk="United States")
    classifier = _FakeClassifier(
        {
            "United States": AssertionClassification(
                fit="Mixed", confidence=0.5, is_relevant=False, relevance_confidence=0.9
            ),
        }
    )

    result = classify_and_filter([irrelevant], classifier)

    assert result == []


def test_relevant_wrong_discipline_assertion_is_kept_as_poor() -> None:
    """A concrete backend/SOA quote is relevant to craft_direction and scored Poor —
    it is evidence, not noise, and must survive filtering."""
    backend_quote = _extracted(
        target="craft_direction", chunk="We run a Java SOA backend with REST services."
    )
    classifier = _FakeClassifier(
        {
            "We run a Java SOA backend with REST services.": AssertionClassification(
                fit="Poor", confidence=0.85, is_relevant=True, relevance_confidence=0.9
            ),
        }
    )

    result = classify_and_filter([backend_quote], classifier)

    assert len(result) == 1
    assert result[0].fit == "Poor"
    assert result[0].confidence == 0.85


def test_low_confidence_irrelevant_verdict_is_kept_not_dropped() -> None:
    """Below the drop threshold, an uncertain 'irrelevant' verdict is not trusted —
    the assertion stays in the pool rather than being silently discarded."""
    ambiguous = _extracted(target="agentic", chunk="We value ownership and autonomy.")
    classifier = _FakeClassifier(
        {
            "We value ownership and autonomy.": AssertionClassification(
                fit="Mixed", confidence=0.4, is_relevant=False, relevance_confidence=0.3
            ),
        }
    )

    result = classify_and_filter([ambiguous], classifier)

    assert len(result) == 1


def test_provenance_is_always_model_proposed_regardless_of_classification() -> None:
    extracted = _extracted(target="mission", chunk="We ship weekly.")
    classifier = _FakeClassifier(
        {
            "We ship weekly.": AssertionClassification(
                fit="Strong", confidence=0.9, is_relevant=True, relevance_confidence=0.9
            ),
        }
    )

    result = classify_and_filter([extracted], classifier)

    assert result[0].provenance == "model_proposed"


def test_craft_direction_generic_culture_quote_dropped_backend_quote_kept_poor() -> None:
    """The two real craft_direction cases named in the bearing (Done When #2): a generic
    ownership/culture quote carries no craft_direction evidence and is dropped; a concrete
    wrong-discipline (backend/SOA) quote is relevant and classified Poor, not discarded."""
    generic = _extracted(
        target="craft_direction", chunk="We believe in ownership and radical transparency."
    )
    backend = _extracted(
        target="craft_direction",
        chunk="Our platform team runs a Java SOA backend with REST services.",
    )
    classifier = _FakeClassifier(
        {
            "We believe in ownership and radical transparency.": AssertionClassification(
                fit="Mixed", confidence=0.5, is_relevant=False, relevance_confidence=0.85
            ),
            "Our platform team runs a Java SOA backend with REST services.": AssertionClassification(
                fit="Poor", confidence=0.85, is_relevant=True, relevance_confidence=0.9
            ),
        }
    )

    result = classify_and_filter([generic, backend], classifier)

    assert len(result) == 1
    assert result[0].chunk == "Our platform team runs a Java SOA backend with REST services."
    assert result[0].fit == "Poor"
