# Vector Search with pgvector

## 1. Architectural Role in Agentic RAG

Vector search (Approximate Nearest Neighbor or ANN search) serves as the primary engine for **semantic retrieval**. In enterprise knowledge bases, users rarely phrase questions using the exact terminology present in corporate documentation:
- User asks: *"Can I get compensated for home office ergonomic chairs?"*
- Document states: *"Employees are eligible for a $500 annual remote workspace health stipend."*

Traditional keyword matching scores zero hits for this pair. Vector search projects both into 1024-dimensional continuous vector space using `BAAI/bge-m3`, allowing the retrieval engine to evaluate high geometric similarity.

```
High-Dimensional Semantic Space (1024 Dimensions)
─────────────────────────────────────────────────
[Remote Workspace Health Stipend]  ◄── Distance: 0.14 (High Similarity)
             ▲
             │
   [Query: Home office chair]
             │
             │ Distance: 0.88 (Low Similarity)
             ▼
[Quarterly Financial Audit Report]
```

---

## 2. Approximate Nearest Neighbor (ANN) Indexing Strategies

A brute-force exact nearest neighbor scan computes vector distance against all $N$ records. With $N = 100,000$ and $d = 1024$, each query requires calculating over $10^8$ floating-point operations. ANN indexes trade a fraction of theoretical recall ($\sim 1\%$) for orders-of-magnitude faster execution.

### 2.1 Inverted File Flat (IVFFlat) — Used in Platform Schema
IVFFlat partitions the vector space into $k$ discrete clusters using k-means clustering. Each vector is assigned to its nearest centroid.

```sql
CREATE INDEX ix_document_chunks_embedding_ivfflat 
ON document_chunks 
USING ivfflat (embedding vector_cosine_ops) 
WITH (lists = 100);
```

- **Lists Parameter**: Configured to `lists = 100` in [`alembic/versions/0001_init_schema.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/alembic/versions/0001_init_schema.py). A common sizing rule is $lists \approx \sqrt{N}$ for corpora up to 1M chunks.
- **Search Probing**: At query time, PostgreSQL probes only the nearest `ivfflat.probes` centroids rather than inspecting every cluster:
  ```sql
  SET ivfflat.probes = 10;
  ```
  Increasing `probes` enhances recall toward 99% while increasing query duration proportionally.
- **Index Build Order**: IVFFlat must be built **after** table data is seeded (or rebuilt after major ingestion) so centroids reflect actual vector distributions.

### 2.2 Hierarchical Navigable Small World (HNSW) — Scale Alternative
HNSW constructs a multi-layer graph where lower layers contain all points with short-range connections, and upper layers contain sparse long-range highway links.
- **Advantages**: Superior recall out-of-the-box, no clustering step required, performs reliably even as rows are incrementally inserted.
- **Trade-offs**: Higher build memory and larger disk footprint ($\sim 1.5\times$ IVFFlat).
- **Migration Path**: For deployments scaling beyond 1,000,000 document chunks, the platform provides an automated migration script to transition from IVFFlat to HNSW (`USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`).

---

## 3. Distance Metrics and Vector Operators

pgvector supports three vector operators. The platform standardizes on **Cosine Distance**:

| Operator | Metric | Mathematical Formula | Optimal Use Case |
| :--- | :--- | :--- | :--- |
| `<=>` | **Cosine Distance** | $1 - \frac{u \cdot v}{\|u\|_2 \|v\|_2}$ | **Text Retrieval (BGE-m3)** — length-invariant semantic matching |
| `<#>` | **Negative Inner Product** | $-(u \cdot v)$ | Normalized vectors ($L_2 = 1$) where cosine equals dot product |
| `<->` | **Euclidean / L2 Distance** | $\sqrt{\sum (u_i - v_i)^2}$ | Computer vision, spatial embeddings, physical coordinates |

### Similarity Score Calculation
Cosine distance returns a value where $0.0$ indicates identical vectors and $2.0$ indicates opposite vectors. In [`src/retrieval/dense.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/dense.py), similarity scores are mapped to a $[0, 1]$ range:
$$\text{Score} = 1 - (\text{chunk.embedding} \Leftrightarrow \text{query.embedding})$$

---

## 4. Pre-Filtering vs. Post-Filtering RBAC

A critical vulnerability in enterprise RAG systems is **post-filtering** security controls.

```
Post-Filtering (INSECURE & BROKEN):
1. Vector Index returns Top 10 Nearest Neighbors across ALL enterprise data.
2. Application evaluates permissions in Python.
3. 8 documents are discarded because user lacks clearance.
4. User receives only 2 documents (starving the LLM context), or empty answers!

Pre-Filtering (SECURE - ENFORCED IN OUR PLATFORM):
1. PostgreSQL combines RBAC predicate directly in SQL WHERE clause.
2. Only authorized chunks are evaluated for nearest neighbor ranking.
3. User consistently receives Top K fully authorized documents.
```

The platform executes pre-filtering using a single unified SQL query in [`src/retrieval/dense.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/dense.py):

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

## 5. Failure Modes and Mitigations

### 5.1 Dimensionality Mismatch
- **Failure**: Attempting to insert a 1536-dimensional Ada-002 vector into a `vector(1024)` column causes PostgreSQL to abort the transaction: `ERROR: column "embedding" is of type vector(1024) but expression is of type vector(1536)`.
- **Mitigation**: The embedder dimension is defined in the `Embedder.dim` protocol attribute. Indexing scripts strictly validate array lengths before issuing database bulk inserts.

### 5.2 Cold Index Full Scans
- **Failure**: On an unindexed table, executing `<=>` triggers a full sequential disk scan. On 500,000 chunks, query latency jumps from 12ms to 4.2 seconds.
- **Mitigation**: Database migrations in [`alembic/versions/0001_init_schema.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/alembic/versions/0001_init_schema.py) create the index automatically, and the health check endpoint [`/health/ready`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/apps/api/app/routers/health.py) verifies index presence before marking API pods healthy.

### 5.3 Empty / Degraded IVF Clusters
- **Failure**: If an IVFFlat index is created when the table has only 10 rows, the 100 centroids collapse onto those 10 points. Subsequent inserts of 50,000 rows will perform sub-optimally.
- **Mitigation**: The ingestion pipeline in [`scripts/seed.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/scripts/seed.py) executes `REINDEX INDEX ix_document_chunks_embedding_ivfflat;` immediately following bulk document imports.

---

## 6. Production Checklist

- [x] Vector extension initialized (`CREATE EXTENSION IF NOT EXISTS "vector"`).
- [x] Cosine distance operator (`<=>`) matched with `vector_cosine_ops` index family.
- [x] Pre-retrieval SQL RBAC enforced inside CTE before ranking evaluation.
- [x] Reindex procedure automated following batch ingestion jobs.
- [x] Threshold filtering (`score >= 0.2`) to discard low-confidence matches.
