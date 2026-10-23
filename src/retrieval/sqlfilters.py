"""Shared SQL filter assembly for raw-text retrieval queries.

Optional filters (department, doc_type) are appended as predicates only when
set. The previous pattern (`:department IS NULL OR d.department = :department`
with a NULL bind) made asyncpg raise AmbiguousParameterError on every query
that did not filter by department - so the retrieval SQL never actually
executed successfully before this fix.
"""

from __future__ import annotations


def optional_filter_sql(filters: dict | None) -> tuple[str, dict[str, str]]:
    """Return (sql_fragment, params) for optional equality filters.

    Empty string / no params when nothing is set.
    """
    filters = filters or {}
    parts: list[str] = []
    params: dict[str, str] = {}
    if filters.get("department"):
        parts.append("AND d.department = :department")
        params["department"] = str(filters["department"])
    if filters.get("doc_type"):
        parts.append("AND d.doc_type = :doc_type")
        params["doc_type"] = str(filters["doc_type"])
    return " ".join(parts), params
