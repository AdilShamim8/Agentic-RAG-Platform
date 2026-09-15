# What is RAG? (Retrieval-Augmented Generation)

## 1. The Paradigm Shift: Closed-Book vs. Open-Book AI

Large Language Models (LLMs) operate fundamentally in one of two modes:
1. **Closed-Book Generation (Parametric Memory)**: The LLM relies exclusively on static weights frozen at training time. It cannot access proprietary internal documentation, lacks real-time knowledge, and is prone to confident hallucinations when answering edge-case domain queries.
2. **Open-Book Generation (Non-Parametric Memory / RAG)**: The LLM is provided with factual, authoritative source documents retrieved dynamically from an external knowledge store at inference time. The model acts as a reasoning and synthesis engine grounded strictly in verified context.

```
Closed-Book LLM:
[User Query] ──► [LLM Weights (Cutoff Date)] ──► Hallucinated / Outdated Answer

Open-Book RAG (Our Platform):
[User Query] ──► [Retrieval Engine] ──► [Top Verified Evidence Chunks]
                          │                         │
                          └──────────► [LLM] ◄──────┘
                                        │
                                        ▼
                   [Grounded Answer + Verifiable Citations [1][2]]
```

---

## 2. The Evolution of RAG Architectures

The platform represents the third evolutionary stage of RAG design:

```
┌─────────────────────────┐     ┌─────────────────────────┐     ┌─────────────────────────┐
│       Naive RAG         │     │       Advanced RAG      │     │       Agentic RAG       │
├─────────────────────────┤     ├─────────────────────────┤     ├─────────────────────────┤
│ • Single vector search  │ ──► │ • Hybrid (Dense + FTS)  │ ──► │ • Multi-step planning   │
│ • No reranking          │     │ • Cross-encoder rerank  │     │ • Dynamic tool calling  │
│ • Blind generation      │     │ • Pre-retrieval filters │     │ • Loop & exit detection │
│ • No citation verify    │     │ • Context compression   │     │ • Citation verification │
│ (Prone to hallucination)│     │ (Higher precision)      │     │ (Production Enterprise) │
└─────────────────────────┘     └─────────────────────────┘     └─────────────────────────┘
```

### 2.1 Naive RAG (Baseline 1)
- User asks a question $\rightarrow$ query embedded $\rightarrow$ top 5 vector matches concatenated into prompt $\rightarrow$ LLM outputs an unverified response.
- **Flaws**: Misses exact keywords (acronyms, code IDs); dilutes context with irrelevant chunks; cannot handle multi-part questions; hallucinates citations.

### 2.2 Advanced RAG (Baselines 2–5)
- Introduces parallel PostgreSQL Full-Text Search (FTS) combined via **Reciprocal Rank Fusion (RRF)**.
- Uses **Cross-Encoder Reranking (`BGE-reranker-v2-m3`)** to refine 50 candidates down to 5 high-precision evidence chunks.
- Enforces pre-retrieval SQL RBAC security filters.

### 2.3 Agentic RAG (Baseline 6 — The Platform Standard)
- Replaces static single-pass pipelines with a deterministic **Agent State Machine** (`START` $\rightarrow$ `CLASSIFY` $\rightarrow$ `PLAN` $\rightarrow$ `TOOL_CALL` $\rightarrow$ `RETRIEVE` $\rightarrow$ `RERANK` $\rightarrow$ `EVIDENCE_VALIDATION` $\rightarrow$ `GENERATION` $\rightarrow$ `CITATION_VALIDATION` $\rightarrow$ `END`).
- Evaluates **Evidence Sufficiency**: If retrieved documents do not sufficiently answer all sub-questions, the agent backtracks and executes alternative targeted search queries.
- Verifies every output claim against source chunks via an automated LLM-judge.

---

## 3. RAG vs. Fine-Tuning vs. Long-Context Windows

| Architectural Attribute | Retrieval-Augmented Generation (RAG) | Model Fine-Tuning | Long-Context LLMs (e.g., 2M Tokens) |
| :--- | :--- | :--- | :--- |
| **Knowledge Freshness** | **Instantaneous** (immediate upon document ingestion) | High latency (requires retraining / fine-tuning run) | Instantaneous (loaded in prompt) |
| **Role-Based Access (RBAC)** | **Enforced in SQL WHERE clause** before retrieval | Impossible (knowledge baked globally into weights) | Difficult (entire document corpus in prompt leaks) |
| **Verifiable Citations** | **Exact chunk offsets & URLs** | Opaque (weights cannot cite specific paragraphs) | Approximate |
| **Inference Cost** | **Low** ($0.0007 / query via targeted chunks) | Low per query | Prohibitive ($0.05 to $0.50+ per query) |
| **Latency (p95)** | **Sub-second (1.5s–3s)** | Fast (200ms–1s) | High (10s–30s+ to process 1M tokens) |

**Conclusion**: For organizational knowledge bases subject to ongoing revisions, security classification boundaries, and strict legal citation requirements, RAG is the only viable architectural choice.

---

## 4. End-to-End System Execution Flow

Implemented across the platform's core modules:

```
[1] User Query ────────► [apps/api/app/routers/query.py] (JWT Auth + RBAC Extraction)
                                 │
[2] Classification ────► [src/agents/classifier.py] (Route: Simple vs. Multi-Hop vs. Unsupported)
                                 │
[3] Query Planning ────► [src/agents/planner.py] (Decompose into Sub-Queries & Tool Selection)
                                 │
[4] Parallel Retrieval ─► [src/retrieval/engine.py]
                          ├── Dense: pgvector cosine (<=>) on BGE-m3 vectors
                          └── Lexical: Postgres FTS (ts_rank_cd) on tsv
                                 │
[5] Score Fusion ──────► [src/retrieval/hybrid.py] (Reciprocal Rank Fusion, k=60)
                                 │
[6] Deep Reranking ────► [src/reranking/cross_encoder.py] (BGE-reranker-v2-m3 Top 50 → Top 5)
                                 │
[7] Evidence Gate ─────► [src/agents/evidence_validator.py] (Sufficient? If no, re-plan)
                                 │
[8] Generation ────────► [src/agents/generator.py] (Grounded LLM synthesis with [N] markers)
                                 │
[9] Verification ──────► [src/agents/citation_validator.py] (Audit claims vs. chunk text)
                                 │
[10] Delivery ─────────► User receives verified answer, clickable citations, and OpenTelemetry trace_id
```

---

## 5. Failure Taxonomy and Platform Mitigations

| Failure Category | Failure Manifestation | System Mitigation |
| :--- | :--- | :--- |
| **Retrieval Void** | No relevant documents exist in the corpus for the user's query. | **Abstention Protocol**: Rather than hallucinating, the agent detects zero relevant chunks and safely abstains. |
| **Semantic Drift** | Dense vector search retrieves topically related but non-factual text. | **Cross-Encoder Reranker** filters out topically similar distractor passages. |
| **Temporal Conflict** | An expired 2021 policy contradicts an effective 2024 policy. | **Freshness Scoring** penalizes expired versions by $0.5\times$ and boosts current documents by $1.1\times$. |
| **Unauthorized Access** | User asks for sensitive executive compensation data. | **Pre-Retrieval SQL RBAC** (`rag.access_matches`) completely hides unauthorized chunks. |
| **Hallucinated Citation** | LLM generates `[1]` next to a claim not supported by Chunk 1. | **Citation Validator** strips false citation markers and logs a validation failure. |

---

## 6. Production Checklist

- [x] Dual dense + lexical retrieval running in parallel via `asyncio.gather`.
- [x] Reciprocal Rank Fusion ($k=60$) combining disparate scoring spaces.
- [x] Cross-encoder reranking distilling 50 candidates into top 5 verified chunks.
- [x] Evidence sufficiency gateway before invoking generation.
- [x] Citation validation step verifying marker accuracy before response delivery.
- [x] OpenTelemetry tracing recording latency and token costs per turn.
