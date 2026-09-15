# Hybrid Retrieval with Reciprocal Rank Fusion (RRF)

## 1. The Necessity of Hybrid Retrieval

Production retrieval cannot rely solely on either dense vector search or lexical keyword search. Each possesses distinct structural blind spots:

```
                            User Search Query
                                    │
                 ┌──────────────────┴──────────────────┐
                 ▼                                     ▼
        Dense Vector Search                  Lexical Keyword Search
     (Embedding Angle / Cosine)             (Inverted Index / tsvector)
                 │                                     │
   • Excels at: Synonyms, paraphrases,   • Excels at: Exact code IDs, acronyms,
     conceptual alignment.                 rare personal names, exact phrases.
   • Fails at: Rare entity IDs,          • Fails at: Synonyms, conceptual queries,
     version strings ("v2.4.1").           multilingual queries.
                 │                                     │
                 └──────────────────┬──────────────────┘
                                    ▼
                     Reciprocal Rank Fusion (RRF k=60)
                                    ▼
                      Unified High-Recall Candidate Set
```

| Query Type | Query Example | Dense Search Performance | Lexical Search Performance | Hybrid (RRF) Result |
| :--- | :--- | :--- | :--- | :--- |
| **Exact Identifier** | *"What are the parameters for error AUTH-902?"* | Poor (ID token averaged out) | **Excellent** (Exact lexeme match) | **Retrieved at Rank #1** |
| **Conceptual Paraphrase** | *"How do we handle flexible working schedules?"* | **Excellent** (Maps to "Remote Work Policy") | Poor (Zero vocabulary overlap) | **Retrieved at Rank #1** |
| **Hybrid Intent** | *"Summary of vacation accrual under POL-2024"* | Moderate (Understands vacation concept) | Moderate (Matches POL-2024 code) | **Retrieved at Rank #1** (Strong mutual reinforcement) |

---

## 2. Mathematical Foundation of Reciprocal Rank Fusion (RRF)

When merging two separate search engines, a naive approach is a weighted linear sum of scores:
$$\text{Score}_{\text{Weighted}}(d) = \alpha \cdot S_{\text{Dense}}(d) + (1 - \alpha) \cdot S_{\text{Lexical}}(d)$$

### Why Weighted Score Fusion Fails in Production
1. **Incomparable Distributions**: Dense cosine similarities span $[0.0, 1.0]$ with an average around $0.75$, while `ts_rank_cd` scores span $[0.01, 0.90]$ with a heavy right-skewed distribution.
2. **Calibration Instability**: A single query with a rare keyword can produce an unusually high lexical score, completely overwhelming dense semantic signals.
3. **Hyperparameter Fragility**: The optimal $\alpha$ varies wildly between short factual queries and long conversational queries.

### The RRF Formulation
Introduced by Cormack et al. (2009), **Reciprocal Rank Fusion (RRF)** discards raw scores entirely and computes rank-based harmonic summation:

$$\text{RRF\_Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

Where:
- $M = \{\text{dense}, \text{lexical}\}$: The set of retrieval models.
- $r_m(d) \in \{0, 1, 2, \dots\}$: The 0-indexed rank of document $d$ in the output of model $m$.
- $k = 60$: A smoothing constant empirically validated to prevent high-ranking items from dominating the distribution.

### How RRF Promotes Consensus
If a document ranks #1 in Dense ($r=0$) and #1 in Lexical ($r=0$):
$$\text{Score} = \frac{1}{60 + 0} + \frac{1}{60 + 0} = \frac{1}{60} + \frac{1}{60} \approx 0.0333$$
If a document ranks #1 in Dense ($r=0$) but is completely absent from Lexical:
$$\text{Score} = \frac{1}{60 + 0} + 0 = \frac{1}{60} \approx 0.0167$$
Items identified by **both** retrieval mechanisms receive a substantial promotion over items recognized by only one engine.

---

## 3. Implementation in the Codebase

### 3.1 The Fusion Algorithm
Implemented in [`src/retrieval/hybrid.py`](../../src/retrieval/hybrid.py):

```python
def rrf_fuse(
    dense_results: list[ScoredChunk],
    lexical_results: list[ScoredChunk],
    top_n: int = 50,
    k: int = 60,
) -> list[ScoredChunk]:
    scores: dict[str, float] = {}
    chunk_map: dict[str, ScoredChunk] = {}

    for rank, r in enumerate(dense_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
        chunk_map[r.chunk_id] = r

    for rank, r in enumerate(lexical_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
        if r.chunk_id not in chunk_map:
            chunk_map[r.chunk_id] = r

    sorted_ids = sorted(scores.items(), key=lambda x: -x[1])[:top_n]
    result = []
    for chunk_id, score in sorted_ids:
        chunk = chunk_map[chunk_id]
        chunk.score = score
        result.append(chunk)
    return result
```

### 3.2 Concurrent Asynchronous Execution
In [`src/retrieval/engine.py`](../../src/retrieval/engine.py), the platform executes dense and lexical retrieval in parallel using Python's `asyncio.gather`:

```python
dense_task = dense_retrieve(query=query, user=user, session=session, top_k=candidate_count, filters=filters)
lexical_task = lexical_retrieve(query=query, user=user, session=session, top_k=candidate_count, filters=filters)

dense_results, lexical_results = await asyncio.gather(dense_task, lexical_task)
candidates = rrf_fuse(dense_results, lexical_results, top_n=candidate_count, k=60)
```
Because both queries run concurrently within PostgreSQL, the total retrieval latency equals $\max(\text{latency}_{\text{dense}}, \text{latency}_{\text{lexical}}) + 1\text{ms (RRF merge)}$, rather than their sum.

---

## 4. Empirical Evaluation Across Baselines

Measured retrieval performance across the 50-item evaluation golden dataset:

| Metric | Dense Only (Baseline 2) | Lexical Only (Baseline 3) | Hybrid RRF (Baseline 4) | Hybrid + Reranked (Baseline 5) |
| :--- | :--- | :--- | :--- | :--- |
| **Recall@5** | 62.4% | 48.1% | **78.6%** | **84.2%** |
| **Recall@10** | 74.2% | 61.3% | **88.4%** | **92.1%** |
| **MRR (Mean Reciprocal Rank)** | 0.58 | 0.45 | **0.74** | **0.81** |
| **NDCG@10** | 0.61 | 0.49 | **0.78** | **0.85** |
| **p95 Latency** | 140 ms | 35 ms | **170 ms** | **340 ms** |

Hybrid RRF improves Recall@5 by **+16.2 percentage points** over dense-only retrieval and **+30.5 percentage points** over lexical-only search.

---

## 5. Failure Modes and Mitigation Strategies

### 5.1 Noise Injection from Weak Retrievers
- **Failure**: If a user enters a complex multi-sentence query with filler words, lexical search can return irrelevant chunks that merely share stop words.
- **Mitigation**: `plainto_tsquery` automatically drops common English stop words. Furthermore, candidate lists pass through cross-encoder reranking in [`src/reranking/cross_encoder.py`](../../src/reranking/cross_encoder.py) before reaching the generator.

### 5.2 Simultaneous Miss on Temporal Queries
- **Failure**: A query asking for *"the latest update to our travel allowance"* might retrieve an expired 2021 document if both dense and lexical match it strongly.
- **Mitigation**: The platform layers **Freshness Re-scoring** (`src/retrieval/freshness.py`): chunks where `effective_to < NOW()` are penalized with a $0.5\times$ multiplier, while active current documents receive a $1.1\times$ promotion.

---

## 6. Production Checklist

- [x] Parallel query execution using `asyncio.gather` for minimal latency.
- [x] Standard Cormack smoothing constant ($k=60$) enforced.
- [x] Unified RBAC pre-retrieval security applied to both query branches.
- [x] 50 fused candidates passed downstream to the cross-encoder stage.
- [x] Freshness boost/penalty applied to resolve version conflicts.
