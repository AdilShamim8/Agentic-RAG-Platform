# Observability

> How this project makes the Agentic RAG pipeline transparent, measurable, and debuggable in production.

## Concept

**Observability** is the ability to understand the internal state of a system from its external outputs. For an Agentic RAG pipeline — which involves multiple LLM calls, database queries, model inference, and agentic decision loops — observability means being able to answer:

- "Why did this query return the wrong answer?"
- "Which step took the longest?"
- "How much did this request cost?"
- "Is the system degrading over time?"

This project implements observability via three pillars: **traces** (what happened), **metrics** (how well the system is performing), and **logs** (detailed event records).

## Why it exists

Without observability:

- A user reports a wrong answer and there is no way to reproduce or inspect the retrieval path.
- Latency regressions are invisible until users complain.
- Cost accumulates without attribution (which query type is most expensive?).
- Agent loops, hallucination spikes, and prompt regressions go undetected.

Observability converts the system from a black box into a transparent, auditable pipeline.

## How it works (in this project)

### Traces — OpenTelemetry + Langfuse

Every `/query` request creates an OpenTelemetry **trace** (identified by a `trace_id` UUID). The trace is a tree of **spans**:

```
trace_id: abc-123
  └── run_agent
        ├── classify_query          (duration: 120ms, model: gpt-4o-mini)
        ├── plan_query              (duration: 200ms, model: gpt-4o-mini)
        ├── tool_call: search_documents
        │     ├── dense_retrieval   (duration: 45ms, chunks_returned: 50)
        │     ├── lexical_retrieval (duration: 30ms, chunks_returned: 30)
        │     ├── rrf_fusion        (duration: 5ms)
        │     └── reranking         (duration: 340ms, candidates: 50, top_k: 5)
        ├── evidence_sufficiency    (duration: 150ms, sufficient: true)
        ├── generate_answer         (duration: 900ms, tokens: 512, cost: $0.0004)
        └── validate_citations      (duration: 180ms, valid: 3/3)
```

Traces are exported to **Langfuse** (self-hosted on `localhost:3001` in dev) via the OpenTelemetry protocol. The Langfuse UI shows the full span tree, latency breakdown, token counts, and cost per request.

Trace attributes set on spans include:

| Attribute | Description |
| --------- | ----------- |
| `rag.query_type` | simple / comparative / temporal / multi-hop |
| `rag.tool_calls` | number of tool calls in this run |
| `rag.chunks_retrieved` | total chunks retrieved |
| `rag.citations_valid` | number of validated citations |
| `rag.failure_type` | `NO_DOCUMENTS`, `HALLUCINATION_DETECTED`, etc. |
| `rag.cost_usd` | estimated cost for this request |
| `rag.latency_ms` | total wall-clock time |

### Metrics — Prometheus

The FastAPI app exposes Prometheus metrics at `/metrics`:

| Metric | Type | Description |
| ------ | ---- | ----------- |
| `rag_query_total` | Counter | Total queries, labelled by `query_type`, `status` |
| `rag_query_latency_seconds` | Histogram | End-to-end latency, labelled by `query_type` |
| `rag_failure_total` | Counter | Failures, labelled by `failure_type` |
| `rag_llm_latency_seconds` | Histogram | LLM call latency |
| `rag_rerank_latency_seconds` | Histogram | Reranker latency |
| `rag_retrieval_latency_seconds` | Histogram | Retrieval latency (dense + lexical + RRF) |
| `rag_tokens_total` | Counter | Token usage, labelled by `model`, `direction` (prompt/completion) |
| `rag_cost_usd_total` | Counter | Estimated cost accumulated |

Prometheus scrapes `/metrics` every 15 seconds. Alert rules fire on:
- `RAGQueryLatencyHigh` — p95 latency > 5 seconds for 5 minutes.
- `RAGFailureRateHigh` — failure rate > 5% for 5 minutes.
- `RAGHallucinationSpike` — hallucination failure rate > 1% for 10 minutes.

### Logs — structlog

All application logs use **structlog** with JSON output. Every log line includes:

```json
{
  "timestamp": "2025-01-15T10:23:45.123Z",
  "level": "info",
  "event": "query_completed",
  "trace_id": "abc-123",
  "user_id": "u-456",
  "query_type": "multi_hop",
  "latency_ms": 1820,
  "citations": 3
}
```

Sensitive fields (API keys, passwords, user emails) are redacted by the structlog redaction filter before output.

### Audit logs

Every privileged action (document upload, role assignment, memory write/delete) is appended to the `audit_logs` database table. Audit logs are immutable (no `UPDATE` or `DELETE` is ever issued against this table).

## Where it appears in the code

| File | Purpose |
| ---- | ------- |
| `src/observability/tracer.py` | OpenTelemetry span management |
| `src/observability/metrics.py` | Prometheus metric definitions |
| `src/core/logging.py` | structlog configuration and redaction filter |
| `apps/api/app/main.py` | Prometheus exporter middleware |
| `configs/base/config.yaml` | `langfuse_host`, `prometheus_enabled` settings |
| `docker-compose.yml` | Langfuse + Langfuse Postgres services |

## Trade-offs

### OpenTelemetry + Langfuse vs. LangSmith

- **Langfuse** (this project): open-source, self-hosted, GDPR-friendly, no vendor lock-in.
- **LangSmith**: managed, tighter LangChain integration, better UI for chained LLM calls.

We chose Langfuse (see ADR-007) because it is open-source and can be self-hosted, which matters for organizations with data privacy requirements.

### Sampling vs. full tracing

- **Full tracing** (this project): every request is traced. No missed incidents. Higher storage cost.
- **Sampling**: trace 10% of requests. Lower cost. Misses rare bugs.

At current scale (< 1000 queries/day), full tracing is affordable. At higher scale, switch to tail-based sampling (trace all failures + 10% of successes).

## Failure modes

| Failure | Impact | Mitigation |
| ------- | ------ | ---------- |
| Langfuse down | Traces lost | Tracing is non-blocking; the query still succeeds |
| Prometheus unreachable | Alerts delayed | `/health/ready` still works; check `/metrics` manually |
| Log volume overflow | Disk full | Rotate logs with `max-size: 100m`, ship to external aggregator |

See `docs/operations/runbook.md` for the Langfuse down runbook.

## Further reading

- OpenTelemetry documentation — https://opentelemetry.io/docs/
- Langfuse documentation — https://langfuse.com/docs
- Charity Majors, "Observability Engineering" (O'Reilly, 2022) — the canonical book on modern observability.
- Google SRE Book, Chapter 6: "Monitoring Distributed Systems" — foundational principles.
