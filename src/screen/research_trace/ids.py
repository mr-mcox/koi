"""Stable id derivation for a research trace file.
company name is not known until `identify_opening` runs; the staging
directory uses the hash so no premature guess at a company name is made.
"""

import hashlib

_RESEARCH_TRACE_HASH_LEN = 12


def derive_research_trace_id(url: str) -> str:
    """Stable opaque id for the research trace of `url`. Same URL → same id.

    The truncated SHA-1 is short enough for a directory name and large
    enough to make collisions practically impossible at the expected URL volume.
    """
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:_RESEARCH_TRACE_HASH_LEN]
