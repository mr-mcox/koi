"""Stable id derivation for a transcript file.
company name is not known until `identify_opening` runs; the staging
directory uses the hash so no premature guess at a company name is made.
"""

import hashlib

_TRANSCRIPT_HASH_LEN = 12


def derive_transcript_id(url: str) -> str:
    """Stable opaque id for the transcript of `url`. Same URL → same id.

    The truncated SHA-1 is short enough for a directory name and large
    enough to make collisions practically impossible at the expected URL volume.
    """
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:_TRANSCRIPT_HASH_LEN]
