"""Which URLs intake accepts, decided at submit time.

See decisions.md W7 for the policy and why it is enforced only here.
"""

from collections.abc import Iterable
from urllib.parse import urlparse

# Hosts that answer automated clients with a bot-protection challenge. We honor
# the refusal instead of retrying into it. Suffix-matched on domain boundaries.
DECLINED_HOSTS: tuple[str, ...] = ("hiringcafe.com",)

# Large aggregator/job-board hosts whose pages are mostly site chrome (nav menus,
# "similar jobs" sidebars, login/signup links, logo images) repeated across every
# page from that host — never company content. Distinct from DECLINED_HOSTS: these
# hosts *do* answer automated fetches, the markdown they return is just not signal.
# Measured on live research traces (outbound-link-backlog scouting F14, F15): the
# backlog's pre-score candidate cap drops the link a human would follow once pages
# from these hosts flood the link pool; filtering these hosts out fixed every
# observed case.
AGGREGATOR_CHROME_HOSTS: tuple[str, ...] = (
    "linkedin.com",
    "hiringcafe.com",
    "levels.fyi",
    "remoterocketship.com",
    "img.logo.dev",
    "startup.jobs",
)

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
