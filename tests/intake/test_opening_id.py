"""Opening-id derivation tests."""

from screen.intake.opening_id import derive_opening_id


def test_slug_from_title() -> None:
    aid = derive_opening_id("Staff Platform Engineer", "https://x.example/jobs/1")
    parts = aid.rsplit("-", 1)
    assert parts[0] == "staff-platform-engineer"
    assert len(parts[1]) == 6  # SHA-1[:6] suffix always present


def test_two_distinct_urls_differ() -> None:
    a = derive_opening_id("Engineer", "https://x.example/jobs/1")
    b = derive_opening_id("Engineer", "https://x.example/jobs/2")
    assert a != b


def test_same_inputs_are_deterministic() -> None:
    a = derive_opening_id("SRE", "https://x.example/jobs/7")
    b = derive_opening_id("SRE", "https://x.example/jobs/7")
    assert a == b


def test_slug_drops_punctuation_collapses_runs() -> None:
    aid = derive_opening_id("Staff  Engineer!! (Backend)", "https://x.example/j")
    parts = aid.rsplit("-", 1)
    assert parts[0] == "staff-engineer-backend"


def test_short_title_gets_suffix() -> None:
    aid = derive_opening_id("X", "https://x.example/j")
    parts = aid.rsplit("-", 1)
    assert parts[0] == "x"
    assert len(parts[1]) == 6
