# Technology Selection & Architectural Trade-off Analysis

> Comprehensive evaluation and rationale for every foundational library, database engine, machine learning model, and framework chosen for the Agentic RAG Platform.

---

## 1. Executive Summary: The Core Stack

| Architectural Concern | Selected Technology | Primary Trade-off Rationale | Key Reference |
| :--- | :--- | :--- | :--- |
| **Backend Runtime** | Python 3.11 + FastAPI + Pydantic v2 | Async I/O concurrency, strict runtime typing, ML/PyTorch ecosystem synergy. | [`src/`](../../src/) |
| **Unified Storage** | PostgreSQL 16 + `pgvector` 0.7 + GIN | Single datastore for relational RBAC, vector embeddings, and full-text search. | [ADR-001](../decisions/0001-postgresql-single-store.md) |
| **Dense Embeddings** | `BAAI/bge-m3` (Local PyTorch) | 1024-dim dense geometry, multilingual (100+ languages), zero external API cost. | [`embeddings.md`](../learning/embeddings.md) |
| **Cross-Encoder Reranker**| `BAAI/bge-reranker-v2-m3` | Joint query-document attention scoring; improves Recall@5 from 62.4% to 84.2%. | [ADR-003](../decisions/0003-cross-encoder-reranking.md) |
| **Agent Orchestration** | Custom State Machine | Pure Python deterministic state transitions; eliminates framework lock-in. | [ADR-004](../decisions/0004-custom-agent-state-machine.md) |
| **LLM Synthesis Engine** | OpenAI `gpt-4o-mini` + Provider Bridge| High reasoning capability at low unit cost (~$0.0007/query); swappable via provider interface. | [`src/llm/provider.py`](../../src/llm/provider.py) |
| **User Interface** | Next.js 14 + React + Tailwind CSS | Server-side rendering, responsive conversational chat, citation inspection inspector. | [`apps/web/`](../../apps/web/) |
| **Distributed Telemetry**| OpenTelemetry + Self-Hosted Langfuse | Vendor-neutral wire protocol; local trace sovereignty and LLM cost accounting. | [ADR-007](../decisions/0007-opentelemetry-tracing.md) |
| **Low-Latency Cache** | Redis 7 Alpine | In-memory key-value caching of embedding vectors, query results, and rate limits. | `docker-compose.yml` |
| **Database Migrations** | Alembic + SQLAlchemy 2.0 | Declarative asynchronous schema migrations with reversible downgrade operations. | [`alembic/`](../../alembic/) |
| **Document Ingestion** | Docling (PDF) + Trafilatura (HTML) | Layout-aware structural parsing of tables, headings, and Markdown conversion. | [`src/ingestion/loaders.py`](../../src/ingestion/loaders.py) |
| **Evaluation Framework**| Ragas + Golden Benchmark | Automated CI quality gates measuring Faithfulness, Recall@K, and Hallucination rate. | [`rag-evaluation.md`](../learning/rag-evaluation.md) |

---

## 2. In-Depth Architectural Evaluations

### 2.1. Unified PostgreSQL vs. Specialized Vector Databases (Pinecone / Qdrant)
* **The Dilemma**: Specialized vector databases (Pinecone, Milvus, Qdrant) advertise high standalone vector search throughput ($>10,000$ QPS).
* **Why We Chose PostgreSQL + pgvector**:
  1. **Transactional Integrity & Pre-Filtering**: Enterprise RAG requires strict RBAC. In PostgreSQL, access authorization (`rag.access_matches()`) and vector similarity search execute in a single atomic SQL query. Specialized vector databases require either syncing relational permissions to the external vector index or performing insecure post-retrieval filtering.
  2. **Reduced Operational Surface**: Eliminates secondary database operational burdens, replication sync lag, and distributed state consistency issues.
  3. **HNSW Performance**: With `pgvector` 0.7, HNSW index construction and query latency (<15ms) easily satisfy production SLA demands for corporas under 10M chunks.

### 2.2. Custom State Machine vs. LangChain / LangGraph
* **The Dilemma**: LangChain and LangGraph provide pre-built abstractions for agent loops.
* **Why We Chose Custom State Machine**:
  1. **Deterministic Halting**: Third-party agent frameworks frequently suffer from non-deterministic recursion, complex dependency chains, and opaque internal state.
  2. **Zero Abstraction Tax**: Our entire state machine (`src/agents/orchestrator.py`) is implemented in <350 lines of explicit, typed Python code with four strict mathematical invariants (step ceiling, tool invocation cap, wall-clock timeout, SHA-256 loop detection).
  3. **Maintainability**: Eliminates constant breaking changes across third-party framework release cycles.

### 2.3. BGE-m3 & Local Cross-Encoder vs. Proprietary Cloud APIs (Cohere / OpenAI)
* **The Dilemma**: Using cloud APIs (Cohere Rerank, OpenAI Embeddings) requires zero local infrastructure.
* **Why We Chose Local Models**:
  1. **Unit Economics**: Embedding and reranking are zero-cost operations ($0.00 API fees) running on existing CPU worker pools.
  2. **Data Privacy**: Raw document chunks and queries are embedded within the VPC boundary, never transmitted across third-party API networks.
  3. **Latency Consistency**: Eliminates external network roundtrips for intermediate candidate filtering.

### 2.4. Streaming Architecture: Server-Sent Events (SSE)
* **Design Decision**: To eliminate perceived response latency (p95 generation time ~1.8s), the API gateway implements Server-Sent Events (SSE) via `StreamingResponse`. The client receives the initial token stream in <300ms, while verified citation metadata and trace attributes are transmitted in the final closing event frame.

---

## 3. Explicit Technology Rejections

1. **GraphQL**: Rejected in favor of RESTful endpoints. The platform data model is well-defined and hierarchical; GraphQL adds unnecessary schema mapping overhead.
2. **LangSmith (Cloud SaaS)**: Rejected in favor of self-hosted Langfuse to preserve customer data sovereignty and eliminate per-trace SaaS subscription fees.
3. **Heavy Distributed Task Queues (Celery/RabbitMQ)**: For current ingestion volumes, asynchronous background workers using native Python `asyncio` queues provide sufficient throughput without message broker operational overhead.

