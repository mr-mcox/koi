"""Company-id derivation tests."""

from screen.intake.company_id import derive_company_id


def test_slug_from_normal_name() -> None:
    """A name with alphanumeric characters slugifies to lowercase with
    non-alphanumerics collapsed to single hyphens and stripped at edges."""
    assert derive_company_id("Anthropic", "https://anthropic.com/careers") == "anthropic"


def test_slug_drops_punctuation_and_collapses_runs() -> None:
    assert derive_company_id("A.!B  C--D", "https://x.example/jobs") == "a-b-c-d"


def test_short_slug_gets_sha1_suffix() -> None:
    """When the slug is shorter than 3 characters, fall back to SHA-1(URL)
    prefix to guarantee uniqueness across companies with similar templates."""
    aid = derive_company_id("AB", "https://www.ab.co/jobs/1")
    bid = derive_company_id("AB", "https://www.ab.co/jobs/2")
    # Both same slug "ab" → both reach the <3 path → distinct SHA-1 suffixes.
    assert aid.startswith("ab-")
    assert bid.startswith("ab-")
    assert aid != bid
    assert len(aid.split("-", 1)[1]) == 8
    assert len(bid.split("-", 1)[1]) == 8


def test_empty_slug_falls_back_to_sha1() -> None:
    """All-punctuation name produces empty slug; fall back entirely to
    SHA-1(URL) prefix so directory is still distinguishable."""
    aid = derive_company_id("!!!", "https://www.example.com/jobs/42")
    assert aid.startswith("-")
    suffix = aid.lstrip("-")
    assert len(suffix) == 8
    # Distinct URL → distinct suffix.
    aid_b = derive_company_id("!!!", "https://www.example.com/jobs/43")
    assert aid != aid_b


def test_long_slug_unchanged() -> None:
    """Slugs >= 3 chars stay slug-only; same URL doesn't add anything."""
    name = "CDE"
    url = "https://cde.example.com/jobs"
    assert derive_company_id(name, url) == "cde"


def test_unicode_name_lowercases_and_drops_diacritics_unsupported() -> None:
    """Non-ASCII letters are not in `[^a-z0-9]+` after lowercase; they end
    up as hyphens and the regex collapses runs. This may surprise; the
    contract is documented and explicit: ASCII-safe slugs only."""
    # "Café" → "caf" via ASCII-only regex (é is not [a-z0-9]).
    assert derive_company_id("Café", "https://x.example/jobs") == "caf"
