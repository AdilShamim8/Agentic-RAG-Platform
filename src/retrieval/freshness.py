"""Document freshness — as-of semantics.

Retrieval must never surface chunks outside their document's effective
window. Enforcement happens in the retrieval SQL WHERE clause (before
ranking), not as a post-hoc score penalty:

- Default (no date filters): only *currently effective* chunks are
  returned — effective_from <= today (or null) AND effective_to >= today
  (or null). Future-dated and expired documents are excluded entirely.
- Explicit date range (filters carrying effective_from_gte /
  effective_to_lte, set by the search_by_date tool): interval-intersection
  semantics — a chunk matches if its effective window intersects the
  requested range. This lets historical queries see superseded versions.

`apply_freshness_boost` remains as a mild ranking preference (currently
effective 1.1x, expired 0.5x) for range mode, where mixed windows can
legitimately coexist.

Boundary dates use the database server's CURRENT_DATE for the default
window; keep DB and app containers timezone-aligned (both default to UTC
in this stack). `date.today()` in the boost uses the app-server date.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.retrieval.types import ScoredChunk

_RANGE_KEYS = ("effective_from_gte", "effective_to_lte")


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_date_filters(filters: dict | None) -> tuple[date | None, date | None]:
    """Extract (from, to) from search_by_date-style filters.

    Returns (None, None) when no explicit range was requested.
    """
    filters = filters or {}
    eff_from = filters.get("effective_from_gte")
    eff_to = filters.get("effective_to_lte")
    return (
        _as_date(eff_from) if eff_from is not None else None,
        _as_date(eff_to) if eff_to is not None else None,
    )


def effective_window_sql(filters: dict | None) -> tuple[str, dict[str, Any]]:
    """Build the effective-window WHERE fragment.

    Returns (sql_fragment, bind_params). Append the fragment to the query's
    WHERE clause and merge the params into the bind dict.
    """
    range_from, range_to = parse_date_filters(filters)
    if range_from is None and range_to is None:
        # Default: currently-effective documents only (server date).
        return (
            "AND (d.effective_from IS NULL OR d.effective_from <= CURRENT_DATE)"
            " AND (d.effective_to IS NULL OR d.effective_to >= CURRENT_DATE)",
            {},
        )
    # Explicit range: interval intersection. A null bound is open-ended.
    frag = "AND (d.effective_from IS NULL OR d.effective_from <= :eff_to)"
    frag += " AND (d.effective_to IS NULL OR d.effective_to >= :eff_from)"
    return frag, {"eff_from": range_from, "eff_to": range_to}


def is_currently_effective(chunk: ScoredChunk, today: date | None = None) -> bool:
    """Python-side check mirroring the SQL predicate (used by tests)."""
    today = today or date.today()
    if chunk.effective_from is not None and chunk.effective_from > today:
        return False
    return not (chunk.effective_to is not None and chunk.effective_to < today)


def apply_freshness_boost(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    """Apply freshness-aware score adjustments.

    - If effective_to < today: 0.5x penalty (expired)
    - If effective_from <= today AND effective_to is null or >= today: 1.1x boost (currently effective)
    - Otherwise (future-dated): 1.0x (no change)
    """
    today = date.today()
    for c in chunks:
        if c.effective_to is not None and c.effective_to < today:
            c.score *= 0.5
        elif (
            c.effective_from is not None
            and c.effective_from <= today
            and (c.effective_to is None or c.effective_to >= today)
        ):
            c.score *= 1.1

    # Re-sort after score adjustment
    chunks.sort(key=lambda x: -x.score)
    return chunks
