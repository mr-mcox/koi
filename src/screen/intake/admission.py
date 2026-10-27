"""Which URLs intake accepts, decided at submit time.

See decisions.md W7 for the policy and why it is enforced only here.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

# Hosts that answer automated clients with a bot-protection challenge. We honor
# the refusal instead of retrying into it. Suffix-matched on domain boundaries.
DECLINED_HOSTS: tuple[str, ...] = ("hiringcafe.com",)

_ATS_EXAMPLES = "Greenhouse, Lever, Ashby, Workday"


def declined_host_for(url: str, declined_hosts: Iterable[str] = DECLINED_HOSTS) -> str | None:
    """The declined host `url` belongs to, or None."""
    host = (urlparse(url).hostname or "").lower()
    for declined in declined_hosts:
        if host == declined or host.endswith(f".{declined}"):
            return declined
    return None


def declined_submission_message(host: str) -> str:
    """What the operator sees instead of a new queue row."""
    return (
        f"Not queued: {host} declines automated access. Open the posting there "
        f"and submit the employer's own link ({_ATS_EXAMPLES}) instead."
    )
