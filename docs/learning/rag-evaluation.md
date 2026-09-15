# Evaluation Framework for Production RAG

## 1. The Three Pillars of RAG Evaluation

In production RAG systems, empirical evaluation separates engineering from intuition. The platform implements an end-to-end evaluation harness structured around three distinct evaluation tiers:

```
                            Evaluation Framework
                                     │
      ┌──────────────────────────────┼──────────────────────────────┐
      ▼                              ▼                              ▼
[1] Retrieval Metrics          [2] Generation Metrics         [3] System & Agent Metrics
  • Recall@K                     • Faithfulness                 • p50/p95/p99 Latency
  • Precision@K                  • Citation Correctness         • Token Consumption
  • Mean Reciprocal Rank (MRR)   • Citation Completeness        • Dollar Cost per Query
  • NDCG@K                       • Hallucination Rate           • Tool-Call Count
                                 • Abstention Accuracy          • Agent Loop Frequency
```

---

## 2. Mathematical Formulations of Retrieval Metrics

Implemented in [`src/evaluation/retrieval_metrics.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/evaluation/retrieval_metrics.py):

### 2.1 Recall@K
Measures the proportion of all ground-truth relevant chunks that appear within the top $K$ retrieved candidates:
$$\text{Recall@K} = \frac{|\text{Retrieved}_{1..K} \cap \text{Relevant}|}{|\text{Relevant}|}$$

### 2.2 Precision@K
Measures the proportion of retrieved candidates within top $K$ that are actually relevant:
$$\text{Precision@K} = \frac{|\text{Retrieved}_{1..K} \cap \text{Relevant}|}{K}$$

### 2.3 Mean Reciprocal Rank (MRR)
Evaluates where the *first* relevant chunk appears in the ranked candidate list:
$$\text{MRR} = \frac{1}{\text{rank}_1}$$
Where $\text{rank}_1$ is the 1-based index of the first relevant document. If no relevant item is retrieved, $\text{MRR} = 0.0$.

### 2.4 Normalized Discounted Cumulative Gain (nDCG@K)
Accounts for the specific positional placement of relevant items, penalizing relevant chunks that appear lower in the candidate list:
$$\text{DCG@K} = \sum_{i=1}^K \frac{\mathbb{I}(\text{chunk}_i \in \text{Relevant})}{\log_2(i + 1)}$$
$$\text{nDCG@K} = \frac{\text{DCG@K}}{\text{IDCG@K}}$$
Where $\text{IDCG@K}$ is the ideal maximum possible DCG score where all relevant items occupy ranks $1 \dots \min(K, |\text{Relevant}|)$.

---

## 3. Generation Metrics and LLM-as-a-Judge

Implemented in [`src/evaluation/generation_metrics.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/evaluation/generation_metrics.py):

| Metric | Evaluation Method | Target Threshold | Description |
| :--- | :--- | :--- | :--- |
| **Faithfulness** | LLM-Judge (Ragas-calibrated) | $\ge 0.85$ (CI Gate) | Ratio of claims in the generated answer directly supported by evidence chunks. |
| **Citation Correctness** | LLM-Judge (`citation_correctness`) | $\ge 0.90$ | Verifies that each `[N]` marker maps strictly to a chunk supporting that specific statement. |
| **Citation Completeness** | LLM-Judge | $\ge 0.85$ | Verifies that all factual claims made in the answer carry appropriate citations. |
| **Hallucination Rate** | LLM-Judge (`HALLUCINATION_PROMPT`) | $\le 0.05$ | Proportion of unsupported or fabricated claims: $\frac{\text{unsupported claims}}{\text{total claims}}$. |
| **Abstention Correctness** | Exact evaluation | $\ge 0.95$ | For negative queries with no supporting documents, confirms the agent safely abstains. |

---

## 4. The 50-Item Golden Evaluation Dataset

The platform benchmarks retrieval and generation using [`evals/datasets/golden.jsonl`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/evals/datasets/golden.jsonl), spanning 10 distinct operational categories:

1. **`simple_factual`**: Single-hop lookups with verbatim answers in corporate policies.
2. **`semantic`**: Conceptual queries with zero lexical overlap with target documents.
3. **`exact_match`**: Code IDs, error codes (`AUTH-403`), and alphanumeric identifiers.
4. **`temporal`**: Questions where answering requires choosing the latest active version over an expired version.
5. **`multi_hop`**: Questions requiring facts synthesized across two or more separate documents.
6. **`comparative`**: Explicit trade-off comparisons across multiple projects or architectural options.
7. **`negative_unsupported`**: Legitimate-sounding questions regarding topics absent from the corpus (testing abstention).
8. **`ambiguous`**: Incompletely specified questions testing clarification or structured decomposition.
9. **`adversarial`**: Prompt injection attempts, rule overrides, and extraction attacks.
10. **`permission_sensitive`**: Queries probing cross-role data access (e.g., student querying staff compensation).

---

## 5. Continuous Integration (CI) Quality Gates

To prevent regressions in prompt engineering, embedding configurations, or chunking parameters:

```
Pull Request Created
        │
        ▼ (.github/workflows/ci.yml)
[eval-smoke job] ──► Runs 10-item golden dataset subset (< 4 minutes)
        │
        ├──► Faithfulness ≥ 0.85  ──► CI Status: PASS (Merge Allowed)
        │
        └──► Faithfulness < 0.85  ──► CI Status: FAIL (Build Blocked)
```

Nightly evaluations execute the full 50-item dataset across all 6 baselines via [`.github/workflows/eval.yml`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/.github/workflows/eval.yml), recording telemetry to Langfuse and storing comparative Markdown artifacts.

---

## 6. Production Checklist

- [x] Automated calculation of Recall@K, Precision@K, MRR, and nDCG@K.
- [x] Zero-temperature LLM-judge for citation correctness and hallucination detection.
- [x] 50-item golden dataset covering 10 distinct functional query categories.
- [x] Automated CI quality gate failing builds when faithfulness drops below 0.85.
- [x] System telemetry tracking p50/p95 latency, token counts, and dollar cost per query.
