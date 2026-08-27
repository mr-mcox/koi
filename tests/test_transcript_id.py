"""transcript_id derivation tests."""

import hashlib

from screen.intake.transcript_id import derive_transcript_id


def test_derive_transcript_id_is_stable_for_same_url() -> None:
    url = "https://example.com/jobs/42"
    assert derive_transcript_id(url) == derive_transcript_id(url)


def test_derive_transcript_id_differs_for_different_urls() -> None:
    a = derive_transcript_id("https://example.com/jobs/42")
    b = derive_transcript_id("https://example.com/jobs/99")
    assert a != b


def test_derive_transcript_id_is_truncated_sha1() -> None:
    url = "https://example.com/jobs/42"
    expected = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    assert derive_transcript_id(url) == expected


def test_derive_transcript_id_length_is_short_enough_for_path_use() -> None:
    """Wall-6 (id-as-path): the id wins when used as a directory name.

    12 hex chars is short enough to grep, long enough to avoid collisions
    (≈ 5×10^13 urls before a 50% collision chance).
    """
    assert len(derive_transcript_id("https://example.com/")) == 12


def test_derive_transcript_id_strips_trailing_whitespace_only_for_equality() -> None:
    """Trivial case: same URL with vs without trailing slash produces
    different ids (URLs are not canonicalized here — caller responsibility).

    This is a documented property, not a bug: the id is the *opaque hash*
    of the input string. If canonicalization is ever wanted, it lives
    upstream, not here.
    """
    assert derive_transcript_id("https://example.com/abc") != derive_transcript_id(
        "https://example.com/abc/"
    )
