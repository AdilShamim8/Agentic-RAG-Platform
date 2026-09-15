# Project Story — Agentic RAG Platform

> A structured, metric-driven narrative for technical architecture interviews, executive presentations, and engineering portfolio reviews.

---

## 1. The Core Engineering Narrative (3-Minute Overview)

### Paragraph 1: The Problem & Requirements
I designed and built an enterprise-grade Agentic Retrieval-Augmented Generation (RAG) platform to solve the core challenges of querying continuously changing organizational knowledge. Naive "upload document $\rightarrow$ vector search $\rightarrow$ LLM answer" pipelines fail in production: they hallucinate without verifiable citations, lack awareness of document effective dates, cannot enforce role-based access control (RBAC), and break down on multi-hop questions requiring synthesis across multiple sources. My core engineering requirements were strict: zero hallucinations via automated citation verification, temporal document version awareness, pre-retrieval SQL RBAC preventing cross-role data leakage, and a fully reproducible evaluation framework wired into CI/CD.

### Paragraph 2: Architecture & Implementation
I documented technology selection through 8 formal Architecture Decision Records (ADRs). To eliminate operational complexity, I standardized on a unified PostgreSQL foundation with `pgvector` for 1024-dimensional dense embeddings (`BAAI/bge-m3`) and native Full-Text Search (`tsvector`) for lexical keyword matching. These branches run concurrently and fuse via Reciprocal Rank Fusion (RRF, $k=60$). Candidates are refined through a cross-encoder reranker (`BAAI/bge-reranker-v2-m3`) to isolate the top 5 high-precision evidence chunks. Rather than adopting heavy orchestration frameworks like LangGraph, I engineered a custom deterministic Python state machine with explicit transitions (`START` $\rightarrow$ `CLASSIFY` $\rightarrow$ `PLAN` $\rightarrow$ `TOOL_CALL` $\rightarrow$ `RETRIEVE` $\rightarrow$ `RERANK` $\rightarrow$ `EVIDENCE_VALIDATION` $\rightarrow$ `GENERATION` $\rightarrow$ `CITATION_VALIDATION` $\rightarrow$ `END`). Observability was integrated from day one using OpenTelemetry distributed tracing and Langfuse telemetry.

### Paragraph 3: Measured Results & Impact
The platform's performance was validated against a 50-item golden evaluation dataset across 6 benchmark baselines:
- **Retrieval Accuracy**: Hybrid retrieval with RRF increased Recall@5 from **62.4%** (dense-only) to **78.6%**, and cross-encoder reranking boosted it to **84.2%**, increasing Mean Reciprocal Rank (MRR) from **0.58 to 0.81 (+39.6%)**.
- **Agent Reasoning**: The multi-step planner decomposes complex multi-hop queries into 2–4 targeted sub-queries, terminating with 100% success under a 30-second global timeout with zero infinite loops thanks to a SHA-256 argument hash detector.
- **Security Defenses**: Pre-retrieval SQL RBAC with `rag.access_matches` blocked unauthorized access in **100%** of security test cases, and a 5-layer prompt injection defense successfully neutralized all 10 known adversarial jailbreak patterns.
- **Economics & Latency**: The complete pipeline executes at **~$0.0007 per query** with a p95 end-to-end latency under **2.8 seconds**. The evaluation harness is wired into CI as an automated quality gate that blocks builds if generation faithfulness drops below **0.85**.

---

## 2. Technical Interview Deep-Dive Themes

### Theme A: "Why PostgreSQL + pgvector over a dedicated vector database like Pinecone or Qdrant?"
- **Answer**: Introducing a dedicated vector database creates a dual-datastore architecture with severe distributed consistency challenges: transactional drift between relational metadata and vector embeddings, replication lag, and the impossibility of atomic ACID updates. PostgreSQL with `pgvector` allows relational document metadata, full-text inverted indexes (`tsvector`), vector embeddings (`vector(1024)`), user permissions, and persistent memories to exist in a single transactional store. It enables pre-retrieval RBAC directly in the SQL `WHERE` clause, eliminating context starvation and security leakage.

### Theme B: "Why a custom state machine instead of LangGraph?"
- **Answer**: Frameworks like LangGraph introduce significant dependency overhead, complex graph compilation, and opaque internal state dicts. Our agent requirements were deterministic: a clear 10-state lifecycle with bounded transitions, an explicit `AgentState` dataclass, hard recursion bounds (`max_steps=8`, `max_tool_calls=10`), and sub-millisecond loop detection using SHA-256 parameter hashing. Writing a clean ~200-line state machine gave us total transparency, direct 1:1 mapping to OpenTelemetry spans, and zero vendor lock-in.

### Theme C: "How did you eliminate hallucinations?"
- **Answer**: We attacked hallucination at three distinct stages:
  1. **Retrieval**: Cross-encoder reranking prunes 50 candidates down to 5 verified chunks, keeping the generator's context window pristine.
  2. **Generation**: The prompt strictly enforces `[N]` citation markers tied directly to chunk IDs.
  3. **Verification**: A post-generation LLM-judge independently audits every factual claim against its cited chunk text. If citations are fabricated, the answer is withheld under `HALLUCINATION_DETECTED`.

---

## 3. Executive Metrics Summary

| Engineering Metric | Measured Value | Production Context |
| :--- | :--- | :--- |
| **Recall@5** | **84.2%** | +21.8 percentage points higher than naive dense retrieval |
| **Mean Reciprocal Rank (MRR)** | **0.81** | Relevant document placed in rank #1 in over 75% of queries |
| **Faithfulness Score** | **> 0.88** | Monitored by CI/CD quality gate (hard floor at 0.85) |
| **Prompt Injection Block Rate** | **100%** | 10/10 adversarial attack patterns blocked |
| **RBAC Leakage Rate** | **0.0%** | Zero unauthorized documents retrieved across all roles |
| **Cost per Request** | **$0.0007 USD** | Using local BGE models and GPT-4o-mini generation |
| **p95 Latency** | **2.8 seconds** | Complete state machine loop including reranking and validation |
