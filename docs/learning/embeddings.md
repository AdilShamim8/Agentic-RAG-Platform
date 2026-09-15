# Embeddings in Agentic RAG

## 1. Mathematical and Conceptual Foundation

An embedding is a dense vector representation of text mapped into a continuous high-dimensional vector space ($\mathbb{R}^d$). Unlike traditional sparse representations (e.g., one-hot encoding, bag-of-words) where dimensions correspond to discrete vocabulary tokens, embedding dimensions capture latent semantic, syntactic, and conceptual relationships.

Texts conveying similar concepts occupy proximate locations in vector space, measured via angular proximity:
- **Cosine Distance in pgvector**:
  $$\text{Cosine Distance}(u, v) = 1 - \frac{u \cdot v}{\|u\|_2 \|v\|_2}$$
  In PostgreSQL with the `pgvector` extension, this operator is denoted by `<=>`.
- **Similarity Score Conversion**:
  $$\text{Score} = 1 - (u \Leftrightarrow v) = \frac{u \cdot v}{\|u\|_2 \|v\|_2}$$
  When vectors are $L_2$-normalized ($\|u\|_2 = 1$), the cosine similarity reduces directly to the inner product ($u \cdot v$), which pgvector accelerates using the `<#>` negative inner product operator.

```
       Query: "telecommuting policy"
                   │
                   ▼ (BGE-m3 Embedder)
          [0.042, -0.018, ..., 0.089] ∈ ℝ¹⁰²⁴
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
Chunk A: "remote work guide"   Chunk B: "quarterly revenue"
[0.040, -0.015, ..., 0.085]    [-0.091, 0.072, ..., -0.012]
Cosine Similarity: 0.94        Cosine Similarity: 0.12
(HIGH MATCH)                   (IRRELEVANT)
```

---

## 2. Model Selection: BAAI/bge-m3 vs. Alternatives

The platform standardizes on **`BAAI/bge-m3`** as its primary default embedder, with an optional vendor fallback to **OpenAI `text-embedding-3-large`**.

| Dimension | BAAI/bge-m3 (Default Local) | OpenAI text-embedding-3-large | Cohere embed-english-v3.0 |
| :--- | :--- | :--- | :--- |
| **Vector Dimension** | 1024 | 3072 (configurable) | 1024 |
| **Max Sequence Length** | 8192 tokens | 8191 tokens | 512 tokens |
| **Hosting Model** | Self-hosted (local GPU/CPU) | Managed API | Managed API |
| **Query Cost** | $0.00 (infrastructure only) | $0.00013 / 1k tokens | $0.00010 / 1k tokens |
| **Multilingual Support** | 100+ languages | High | English specialized |
| **Multi-Functionality** | Dense + Lexical + Multi-Vector | Dense only | Dense only |
| **Privacy / Air-Gapped** | Full data isolation | Requires network transit | Requires network transit |

### Why BGE-m3?
1. **Long-Context Window**: 8,192 token context eliminates arbitrary truncation on medium-sized structured document chunks, contracts, and policies.
2. **Dense Vector Quality**: Achieves state-of-the-art MTEB (Massive Text Embedding Benchmark) retrieval benchmarks without incurring recurring per-token inference API costs.
3. **Storage Efficiency**: 1024-dimensional vectors require exactly 4,096 bytes (4 KB) per chunk in FP32 or 2,048 bytes (2 KB) in FP16, keeping HNSW index memory footprint manageable inside PostgreSQL.

---

## 3. Implementation in the Agentic RAG Platform

### 3.1 The Embedder Protocol Abstraction
Defined in [`src/retrieval/embedders.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/embedders.py), the platform uses a vendor-agnostic Python `Protocol` to decouple the indexing and retrieval pipelines from specific ML runtimes:

```python
class Embedder(Protocol):
    dim: int
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

### 3.2 Asynchronous Threadpool Offloading
Local transformer inference (`BGEM3FlagModel`) is synchronous and CPU/GPU-bound. Executing it directly within an `async` route would block the ASGI event loop (preventing concurrent API requests). In [`src/retrieval/embedders.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/embedders.py), execution is delegated to an executor thread:

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(
    None,
    lambda: self._model.encode(texts, batch_size=32, max_length=8192)["dense_vecs"],
)
return result.tolist()
```

### 3.3 Pre-Retrieval SQL RBAC & Dense Querying
In [`src/retrieval/dense.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/dense.py), vector distance calculation is executed strictly inside a PostgreSQL `WITH authorized AS (...)` CTE. Access control policies (`rag.access_matches`) are evaluated in the `WHERE` clause **before** candidate ranking:

```sql
WITH authorized AS (
    SELECT c.id, c.content, c.metadata, c.page, c.section, c.version,
           d.title AS document_title, d.url, d.effective_from, d.effective_to,
           d.access_policy, d.id AS document_id,
           1 - (c.embedding <=> CAST(:q AS vector)) AS score
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.deleted_at IS NULL
      AND rag.access_matches(d.access_policy, :user_role, :user_projects, :user_id)
      AND (:department IS NULL OR d.department = :department)
      AND (:doc_type IS NULL OR d.doc_type = :doc_type)
    ORDER BY c.embedding <=> CAST(:q AS vector)
    LIMIT :k
)
SELECT * FROM authorized
WHERE score >= :threshold
ORDER BY score DESC;
```

---

## 4. Hardware Sizing & Memory Footprint

To estimate PostgreSQL buffer pool and RAM allocation for vector indexing:

$$\text{Vector Storage per Chunk} = 1024 \times 4\text{ bytes (FP32)} = 4,096\text{ bytes} \approx 4\text{ KB}$$

For an organizational corpus of 100,000 document chunks:
- **Raw Vector Table Size**: $100,000 \times 4\text{ KB} = 400\text{ MB}$.
- **HNSW Index Size** ($m=16, \text{ef\_construction}=64$): Approximately $1.2 \times$ to $1.5 \times$ raw vector size $\approx 500\text{ MB}$ to $600\text{ MB}$.
- **Total RAM requirement to keep active index in memory**: $\sim 1\text{ GB}$.

Because the index comfortably fits in system cache, sub-15ms p95 vector scan latencies are achieved on standard compute instances.

---

## 5. Failure Modes and Mitigation Strategies

### 5.1 Out-of-Domain Specialized Acronyms
- **Failure**: Standard pretrained models may project niche organizational acronyms (e.g., `CAP-402`, `SOC2-T3`) into uninformative regions of semantic space.
- **Mitigation**: The platform never relies solely on dense embeddings. It pairs dense search with Postgres Lexical Full-Text Search (`tsvector`) via **Reciprocal Rank Fusion (RRF)** in [`src/retrieval/hybrid.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/hybrid.py).

### 5.2 Asymmetric Query vs. Passage Length
- **Failure**: A 5-word user question may have a distinct embedding signature from a 300-word policy section describing the same topic.
- **Mitigation**: The Agent Planner decomposes complex questions into targeted sub-questions with focused semantic scope, and the chunker maintains consistent semantic paragraph splits (~400 tokens).

### 5.3 Embedding Model Drift
- **Failure**: Changing the embedding model (e.g., migrating from 1536-dim Ada-002 to 1024-dim BGE-m3) invalidates existing vectors. Cosine distance between embeddings from different models is mathematically meaningless.
- **Mitigation**: Embedding dimensions are strictly schema-enforced via PostgreSQL column definitions (`embedding vector(1024)`). Model names and versions are tracked in chunk metadata, and batch re-indexing scripts are provided in [`scripts/ingest.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/scripts/ingest.py).

---

## 6. Production Checklist

- [x] Embedder protocol abstraction with runtime provider selection.
- [x] Async threadpool execution for CPU/GPU-bound encode calls.
- [x] Pre-retrieval SQL RBAC filter in vector query WHERE clause.
- [x] Hard score threshold gate (`score >= 0.2`) to prune irrelevant tail results.
- [x] Dual support for local open-weights (`BGE-m3`) and API-based (`OpenAI`) backends.
- [x] Automatic fallback to mock provider during CI/test execution.
