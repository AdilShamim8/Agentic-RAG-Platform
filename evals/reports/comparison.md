# Evaluation Comparison

Generated from 1 report(s) in `evals/reports/` (latest report per baseline wins).

- Provider mode: **mock**
- Fixture corpus: `evals/datasets/corpus_fixtures.jsonl` (sha256 cb14c3c89a19d022)
- Deterministic metrics only; LLM-judge rubric scores require a real provider and are NOT included here (see docs/reviews/llm_judge_methodology.md).

## Baseline summary

| Baseline | Behavior compliance | Pattern faithfulness | Recall@k | MRR | Source hit rate | Verified citation rate | Unexpected failures | p95 latency (ms) |
|----------|--------------------:|--------------------:|---------:|----:|---------------:|----------------------:|---------------------:|----------------:|
| baseline_1_naive | 0.857 | 0.657 | 0.886 | 0.857 | 0.886 | 1.000 | 0.143 | 2 |
| baseline_2_dense | 0.857 | 0.657 | 0.886 | 0.857 | 0.886 | 1.000 | 0.143 | 2 |
| baseline_3_lexical | 0.592 | 0.400 | 0.486 | 0.486 | 0.486 | 1.000 | 0.408 | 1 |
| baseline_4_hybrid | 0.898 | 0.686 | 0.943 | 0.900 | 0.943 | 1.000 | 0.102 | 2 |
| baseline_5_hybrid_reranked | 0.898 | 0.686 | 0.943 | 0.900 | 0.943 | 1.000 | 0.102 | 2 |
| baseline_6_agentic | 0.959 | 0.686 | 0.857 | 0.857 | 0.857 | 1.000 | 0.041 | 4 |

## Metric definitions

- **Behavior compliance**: fraction of scored rows whose observed behavior matches the expected row behavior (answer/abstain/refuse/...).
- **Pattern faithfulness**: fraction of answerable rows where every '+'-separated term of the expected answer pattern appears in the answer. A deterministic extractive-grounding proxy, NOT a judge score.
- **Recall@k / MRR / source hit**: computed against the expected fixture chunk ids on rows that carry retrieval labels.
- **Verified citation rate**: fraction of emitted citations that passed claim-level verification.
- **Unexpected failures**: agent failures that violate the expected behavior (a safe refusal is NOT a failure).

## Notes and limitations

- All numbers are deterministic under the recorded provider mode; mock-mode answer quality reflects the deterministic extractive generator, not a production LLM.
- **Do not fabricate numbers.** If a metric was not measured, the table says `Not measured.`
- Fault-injection scenario rows (adversarial.jsonl) are covered by the deterministic test suite, not by these judge-free metrics; see docs/reviews/test_matrix.md.
- A safe abstention/refusal on rows expecting content from unauthorized documents counts as compliant behavior, not as a retrieval miss.