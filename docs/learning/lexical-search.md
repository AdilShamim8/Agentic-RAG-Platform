# Lexical Search with PostgreSQL Full-Text Search (FTS)

## 1. Architectural Role in Hybrid RAG

While vector embeddings excel at semantic associations and conceptual paraphrasing, they frequently suffer from **exact term dilution** and **keyword blind spots**. For enterprise documents containing:
- Specific identifiers (e.g., ticket `SEC-892`, policy code `HR-2024-v2`, error `AUTH_ERR_403`)
- Rare personal names, acronyms, and specialized jargon
- Precise numeric thresholds (e.g., `$50,000`, `99.99% SLA`)

lexical search guarantees that exact query tokens match corresponding chunks. In this platform, Lexical Search runs in parallel with Dense Vector Search as the complementary half of the **Hybrid Retrieval** pipeline.

```
                  User Query: "What is the policy in SEC-892?"
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
      Dense Vector Search                     PostgreSQL Lexical FTS
 (Embedding similarity on meaning)         (Exact lexeme token match on SEC-892)
                 │                                       │
     Returns generic security docs             Returns chunk containing "SEC-892"
       (Ranked #14 by distance)                     (Ranked #1 by ts_rank_cd)
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
                      Reciprocal Rank Fusion (RRF k=60)
                                     ▼
                    Target Chunk promoted to Top 1
```

---

## 2. PostgreSQL Full-Text Search Mechanics

The platform leverages PostgreSQL's native FTS engine, eliminating the operational overhead of a separate external search cluster (e.g., Elasticsearch or OpenSearch).

### 2.1 The `tsvector` Data Type
A `tsvector` is a sorted list of distinct normalized words (**lexemes**) stripped of suffixes, punctuation, and stop words:
- Stored on `document_chunks.tsv`.
- Generated during ingestion via `to_tsvector('english', content)`.
- Example: `"The quick brown fox jumped"` $\rightarrow$ `'brown':3 'fox':4 'jump':5 'quick':2`.

### 2.2 The `tsquery` Query Representation
User search queries are parsed into boolean lexeme search expressions:
- **`plainto_tsquery('english', query)`**: Converts raw conversational input into an `AND`-delimited query without requiring users to write SQL syntax.
- Example: `"remote work policy"` $\rightarrow$ `'remot' & 'work' & 'polici'`.

### 2.3 Cover Density Ranking (`ts_rank_cd`)
Unlike standard `ts_rank` which only tallies term frequencies, the platform uses **Cover Density** ranking (`ts_rank_cd`):
$$\text{Score}_{\text{CD}} = \sum \frac{w_i}{\text{span length}}$$
`ts_rank_cd` calculates how close matching query terms appear to one another within the chunk. If "remote" and "policy" appear within the same sentence, the chunk scores significantly higher than if they appear 200 words apart.

---

## 3. Implementation in the Codebase

### 3.1 GIN Indexing Migration
Defined in [`alembic/versions/0001_init_schema.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/alembic/versions/0001_init_schema.py), the `tsv` column is backed by a **Generalized Inverted Index (GIN)**:

```sql
ALTER TABLE document_chunks ADD COLUMN tsv tsvector;
CREATE INDEX ix_document_chunks_tsv ON document_chunks USING GIN(tsv);
```
GIN indexes map each lexeme directly to the list of chunk IDs containing that lexeme, enabling logarithmic sub-5ms lookup times across millions of rows.

### 3.2 SQL Execution and RBAC Enforcement
Implemented in [`src/retrieval/lexical.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/lexical.py), the query joins `documents` and enforces pre-retrieval role access control:

```sql
SELECT c.id, c.content, c.metadata, c.page, c.section, c.version,
       d.title AS document_title, d.url, d.effective_from, d.effective_to,
       d.access_policy, d.id AS document_id,
       ts_rank_cd(c.tsv, plainto_tsquery('english', :q)) AS score
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL
  AND c.tsv @@ plainto_tsquery('english', :q)
  AND rag.access_matches(d.access_policy, :user_role, :user_projects, :user_id)
  AND (:department IS NULL OR d.department = :department)
  AND (:doc_type IS NULL OR d.doc_type = :doc_type)
ORDER BY score DESC
LIMIT :k;
```

### 3.3 Score Normalization
`ts_rank_cd` yields raw floating point numbers typically in the range $[0.01, 0.9]$. In [`src/retrieval/lexical.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/lexical.py), scores are normalized relative to the maximum observed score in the batch:

```python
max_score = max((float(r["score"]) for r in rows), default=1.0)
if max_score > 0:
    for r in rows:
        r["score"] = float(r["score"]) / max_score
```

---

## 4. Architectural Trade-offs: PostgreSQL FTS vs. Dedicated BM25

| Feature | PostgreSQL FTS (`ts_rank_cd`) | Dedicated BM25 (Elasticsearch/OpenSearch) |
| :--- | :--- | :--- |
| **Operational Overhead** | Zero (unified inside PostgreSQL database) | High (JVM cluster, cluster coordination, sync pipeline) |
| **ACID Consistency** | Immediate on transaction commit | Eventual consistency (indexing lag ~1s) |
| **RBAC Integration** | Native SQL joins with permissions tables | Requires external sync or post-query filtering |
| **Term Frequency Saturation** | Linear / Cover Density approximation | Okapi BM25 non-linear saturation curve |
| **Corpus Scale Budget** | Optimal up to ~5-10 million chunks | Scales horizontally to hundreds of millions |

**Decision**: For enterprise scale under 5 million chunks, PostgreSQL FTS provides identical top-5 retrieval precision when paired with a cross-encoder reranker, while eliminating database replication lag and dual-store drift.

---

## 5. Failure Modes and Mitigations

### 5.1 Stop Word Suppression
- **Problem**: Queries composed primarily of common English words (e.g., "to be or not to be", "out of office") may have key tokens stripped by standard dictionaries.
- **Mitigation**: The hybrid pipeline relies on the dense vector embedder (`BGE-m3`) to catch semantic context when lexical queries yield zero or degraded results.

### 5.2 Multilingual Tokenization Mismatch
- **Problem**: `to_tsvector('english', ...)` uses English Snowball stemmers. German, French, or Japanese text will not stem correctly.
- **Mitigation**: In multi-language repositories, store a `language` column on `documents` and dynamically pass the document language to `to_tsvector(:lang, content)`.

### 5.3 Hyphenated Terms & Product Identifiers
- **Problem**: Terms like `v1.0.4-rc1` can be split into multiple tokens (`v1`, `0`, `4`, `rc1`).
- **Mitigation**: Technical code chunks and identifiers are preserved in raw content and ingested with code-aware cleaning in [`src/ingestion/cleaning.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/ingestion/cleaning.py).

---

## 6. Production Checklist

- [x] Inverted GIN index applied on `document_chunks.tsv`.
- [x] Pre-retrieval SQL RBAC enforced before computing candidate limits.
- [x] `plainto_tsquery` used to safely sanitize conversational user queries.
- [x] Parallel execution with dense retrieval via `asyncio.gather` in hybrid service.
- [x] Relative batch normalization applied before passing candidates to RRF fusion.
