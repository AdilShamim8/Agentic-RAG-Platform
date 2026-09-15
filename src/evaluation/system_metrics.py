"""System metrics — p50/p95/p99 latency, token usage, cost, failure rate."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SystemMetrics:
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    avg_tokens_in: float
    avg_tokens_out: float
    avg_cost_usd: float
    total_cost_usd: float
    failure_rate: float
    tool_call_count_avg: float
    retrieval_count_avg: float


def percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile (0..100)."""
    if not values:
        return 0.0
    return float(np.percentile(values, p))


def compute_system_metrics(
    *,
    latencies_ms: list[float],
    tokens_in: list[int],
    tokens_out: list[int],
    costs_usd: list[float],
    failures: int,
    total: int,
    tool_calls: list[int],
    retrievals: list[int],
) -> SystemMetrics:
    return SystemMetrics(
        p50_latency_ms=percentile(latencies_ms, 50),
        p95_latency_ms=percentile(latencies_ms, 95),
        p99_latency_ms=percentile(latencies_ms, 99),
        avg_tokens_in=sum(tokens_in) / max(len(tokens_in), 1),
        avg_tokens_out=sum(tokens_out) / max(len(tokens_out), 1),
        avg_cost_usd=sum(costs_usd) / max(len(costs_usd), 1),
        total_cost_usd=sum(costs_usd),
        failure_rate=failures / max(total, 1),
        tool_call_count_avg=sum(tool_calls) / max(len(tool_calls), 1),
        retrieval_count_avg=sum(retrievals) / max(len(retrievals), 1),
    )
