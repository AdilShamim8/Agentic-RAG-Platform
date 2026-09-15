"""Metrics — re-export from app's Prometheus setup."""

from __future__ import annotations

from apps.api.app.observability.metrics import (
    RAG_COST_USD,
    RAG_FAILURES,
    RAG_QUERY_LATENCY,
    RAG_QUERY_TOTAL,
    record_cost,
    record_failure,
    record_query,
    record_tool_call,
)

__all__ = [
    "RAG_COST_USD",
    "RAG_FAILURES",
    "RAG_QUERY_LATENCY",
    "RAG_QUERY_TOTAL",
    "record_cost",
    "record_failure",
    "record_query",
    "record_tool_call",
]
