import hashlib
import re

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_MIN_SLUG_LEN = 3
_SHA1_URL_PREFIX_LEN = 8


def derive_company_id(name: str, url: str) -> str:
    # The SHA-1 suffix disambiguates two URLs at the same short name;
    # it's appended only when the slug itself is too short to guarantee
    # directory uniqueness from the slug alone.
    slug = _SLUG_PATTERN.sub("-", name.lower()).strip("-")
    if len(slug) >= _MIN_SLUG_LEN:
        return slug
    suffix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:_SHA1_URL_PREFIX_LEN]
    return f"{slug}-{suffix}"
