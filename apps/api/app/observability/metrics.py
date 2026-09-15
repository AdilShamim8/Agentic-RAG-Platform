"""Prometheus metrics — latency, cost, failures, retrieval counts."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

# Metrics (module-level singletons)
RAG_QUERY_TOTAL = Counter(
    "rag_query_total",
    "Total RAG queries",
    ["status", "category"],
)

RAG_QUERY_LATENCY = Histogram(
    "rag_query_latency_seconds",
    "RAG query latency in seconds",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

RAG_RETRIEVAL_COUNT = Counter(
    "rag_retrieval_total",
    "Total retrieval operations",
    ["strategy"],
)

RAG_TOOL_CALLS = Counter(
    "rag_tool_calls_total",
    "Total tool calls",
    ["tool", "status"],
)

RAG_COST_USD = Counter(
    "rag_cost_usd_total",
    "Total USD spent on LLM calls",
)

RAG_FAILURES = Counter(
    "rag_failure_total",
    "Total failures by type",
    ["failure_type"],
)

ACTIVE_REQUESTS = Gauge(
    "rag_active_requests",
    "Currently in-flight requests",
)


def record_query(*, status: str, latency_ms: int, category: str = "unknown") -> None:
    RAG_QUERY_TOTAL.labels(status=status, category=category).inc()
    RAG_QUERY_LATENCY.observe(latency_ms / 1000.0)


def record_cost(usd: float) -> None:
    if usd > 0:
        RAG_COST_USD.inc(usd)


def record_failure(failure_type: str) -> None:
    RAG_FAILURES.labels(failure_type=failure_type).inc()


def record_tool_call(*, tool: str, status: str = "ok") -> None:
    RAG_TOOL_CALLS.labels(tool=tool, status=status).inc()


def setup_metrics(app) -> None:
    """Mount /metrics endpoint on the FastAPI app."""
    app.mount("/metrics", make_asgi_app())
