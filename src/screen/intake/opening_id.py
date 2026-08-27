import hashlib
import re

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_SHA1_URL_PREFIX_LEN = 6


def derive_opening_id(title: str, url: str) -> str:
    slug = _SLUG_PATTERN.sub("-", title.lower()).strip("-")
    suffix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:_SHA1_URL_PREFIX_LEN]
    return f"{slug}-{suffix}"
