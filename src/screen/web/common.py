"""What more than one review-surface feature renders with: the template environment, the
rank-axis glyph, accent hues, and digest-grouped assertions."""

import hashlib
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from screen.api.deps import get_db
from screen.digest.protocol import Digester
from screen.digest.render import render_digest_html
from screen.digest.service import digest_record_for_target
from screen.research.batch import eta_text
from screen.score.types import OpeningRank, ScoringConfig
from screen.store.repo import get_company
from screen.types import Assertion, Company, Opening

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["render_digest_html"] = render_digest_html
templates.env.filters["eta_text"] = eta_text

static_files = StaticFiles(directory=str(Path(__file__).parent / "static"))


def template_context(context: DataclassInstance) -> dict[str, object]:
    """A page's typed context as the mapping a template renders. Shallow, unlike
    `dataclasses.asdict`, so nested dataclasses keep their properties."""
    return {field.name: getattr(context, field.name) for field in fields(context)}


@dataclass(frozen=True)
class DimensionGroup:
    target: str
    digest: str
    digest_version: str | None
    assertions: list[Assertion]


@dataclass(frozen=True)
class BoundaryGlyph:
    """Rank-axis credible-interval bar for one opening in the pool: `low`/`median`/`high`
    are sampled rank quantiles (lower rank is better), and `boundary` is the `top_k`
    cutoff. Percentages are computed against a shared axis so rows are comparable: left
    is best, right is worse. `settledness_alpha`/`settledness_label` say whether the band
    is fully inside the boundary, straddling it, or fully outside."""

    low: float
    median: float
    high: float
    boundary: float | None
    top_k: int
    total: int

    @property
    def _axis_max(self) -> float:
        return float(max(self.total, self.top_k * 2, 3))

    def _pct(self, rank: float) -> float:
        return (self._axis_max - rank) / (self._axis_max - 1.0)

    @property
    def low_pct(self) -> float:
        return self._pct(self.low)

    @property
    def median_pct(self) -> float:
        return self._pct(self.median)

    @property
    def high_pct(self) -> float:
        return self._pct(self.high)

    @property
    def boundary_pct(self) -> float | None:
        return self._pct(self.boundary) if self.boundary is not None else None

    @property
    def settledness_alpha(self) -> float:
        """Fill opacity for the median marker: fully opaque when the whole plausible
        rank band is inside the top-K boundary, faint when it straddles, outline-only
        when even the best plausible case is outside."""
        boundary = self.boundary
        if boundary is None:
            return 1.0
        if self.low <= boundary and self.high <= boundary:
            return 1.0
        if self.high <= boundary < self.low:
            return 0.60
        return 0.0

    @property
    def settledness_label(self) -> str:
        boundary = self.boundary
        if boundary is None:
            return "no boundary yet; rank still takes shape"
        if self.low <= boundary and self.high <= boundary:
            return f"locked into top {int(boundary)}"
        if self.high <= boundary < self.low:
            return f"contesting the top {int(boundary)} boundary"
        return f"outside the top {int(boundary)}"


def boundary_glyph_for_score(
    rank: OpeningRank,
    *,
    top_k: int,
    total: int,
) -> BoundaryGlyph:
    """The glyph for one opening, given the pool's shared `top_k` boundary and size."""
    boundary = float(top_k) if total >= top_k else None
    return BoundaryGlyph(
        low=rank.rank_q90,
        median=rank.rank_q50,
        high=rank.rank_q10,
        boundary=boundary,
        top_k=top_k,
        total=total,
    )


def company_for(conn: sqlite3.Connection, opening: Opening) -> Company:
    """`Opening.company_id` is a foreign key with `PRAGMA foreign_keys = ON`
    (store/db.py) — the referenced company always exists."""
    return cast(Company, get_company(conn, opening.company_id))


def _hue_from_seed(seed: str, *, center: float, spread: float) -> float:
    """Deterministic decorative OKLCH hue (degrees) from a stable id. Styling only —
    never read by the scorer or stored; re-derived on every render."""
    digest = hashlib.sha256(seed.encode()).digest()
    frac = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return round(center + (frac - 0.5) * 2 * spread, 1)


def accent_hues(company_id: str, opening_id: str) -> tuple[float, float]:
    """Company and opening accent hues, both within the koi-orange band (centered
    ~42°). The opening's hue is a small perturbation of its own company's — not an
    independent draw — so a company's openings read as kin, each opening still its
    own shade."""
    company_hue = _hue_from_seed(company_id, center=42, spread=16)
    opening_hue = _hue_from_seed(opening_id, center=company_hue, spread=6)
    return company_hue, opening_hue


def dimension_groups(
    conn: sqlite3.Connection,
    opening_id: str,
    assertions: list[Assertion],
    config: ScoringConfig,
    *,
    digester: Digester,
    rubric_text: str,
    now: datetime,
) -> list[DimensionGroup]:
    """Group assertions by rubric target and attach the cached digest for each group.
    Dimensions are ordered by their declared weight descending (ties broken by slug); any
    target carrying assertions but missing from the weights is appended after. Empty
    declared dimensions still render with a 'not yet examined' digest so the operator can
    see coverage gaps at a glance.
    """
    declared = sorted(
        config.dimension_weights,
        key=lambda slug: (-config.dimension_weights[slug], slug),
    )
    by_target: dict[str, list[Assertion]] = defaultdict(list)
    for a in assertions:
        by_target[a.target].append(a)
    all_targets = list(dict.fromkeys(declared + [a.target for a in assertions]))
    groups: list[DimensionGroup] = []
    for target in all_targets:
        target_assertions = by_target.get(target, [])
        if target_assertions:
            digest_record = digest_record_for_target(
                conn,
                opening_id=opening_id,
                target=target,
                digester=digester,
                rubric_text=rubric_text,
                now=now,
            )
            digest = digest_record.digest
            digest_version = digest_record.id
        else:
            digest = "not yet examined"
            digest_version = None
        groups.append(
            DimensionGroup(
                target=target,
                digest=digest,
                digest_version=digest_version,
                assertions=target_assertions,
            )
        )
    return groups
