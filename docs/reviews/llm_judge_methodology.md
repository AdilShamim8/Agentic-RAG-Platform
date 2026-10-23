# LLM-as-Judge Methodology

Status of every claim in this document is explicit: **implemented + tested**,
**implemented + blocked** (cannot run without a real provider), or
**not implemented** (with a follow-up). Nothing here is aspirational wording
about a capability that does not exist.

## 1. Two-layer evaluation model

This platform separates deterministic measurement from model judgment:

1. **Deterministic layer (implemented + tested, runs in CI on every PR).**
   Computed by `evals/run.py` against the seeded fixture corpus:
   behavior compliance, Recall@k, MRR, expected-source hit rate,
   verified-citation rate, unauthorized-citation count (must be 0), and
   pattern faithfulness (all `'+'`-separated expected terms present in the
   answer - an extractive-grounding proxy, labeled as such in every report).
   A safe abstention/refusal matching the expected row behavior is NOT
   counted as a failure.

2. **LLM-judge layer (implemented + blocked in mock mode).**
   The claim-level citation verifier (`src/agents/citation_validator.py`)
   runs in EVERY query (production included) and fails closed on judge
   errors, malformed output, or omitted (claim, chunk) pairs. The rubric-based
   answer-quality judge (0-4 dimensions below) is implemented in
   `src/evaluation/generation_metrics.py` for real providers; under the
   deterministic mock provider those scores would be meaningless, so the
   runner does not emit them and the reports say so.

Deterministic security assertions are NEVER overridable by a judge: the
evaluator cannot turn an unauthorized citation into a pass, and the
query-time validator cannot verify a citation when its judge fails.

## 2. Judge rubric (answer quality; real providers only)

Each dimension scored 0-4; the judge must return schema-validated JSON.

| Dimension | 0 | 2 | 4 |
|---|---|---|---|
| Factual correctness & completeness | mostly false/irrelevant | partially correct | fully correct for the question and reference criteria |
| Groundedness / faithfulness | claims contradicted or unsupported | mixed support | every material claim supported by authorized evidence |
| Citation correctness | citations missing/fabricated | partial support | all material claims have valid, claim-supporting citations (deterministic ID/range validation stays separate) |
| Instruction & behavior compliance | violates expected behavior | partially follows | correct behavior (answer/clarify/abstain/refuse) |
| Clarity & usefulness | incoherent | partly useful | clear, direct, appropriately scoped |

Calibration for false abstentions (answerable query declined) and unsafe
answers (unsupported content supplied) is reported separately; a long or
confident answer gets no credit by itself.

## 3. Judge integrity rules (implemented)

- The answering prompt and the judge prompt are separate modules; the judge
  never receives the answer model's instructions as its own.
- Retrieved evidence and answers are wrapped and introduced as DATA; the
  citation-verifier prompt explicitly states that instructions inside the
  evidence are not commands (`src/agents/citation_validator.py`).
- Judge output is schema-validated: results must be a list of
  `{claim_index, chunk_id, supported}` rows; anything else, or a missing
  pair, marks that pair unsupported (fail closed). Regression:
  `tests/unit/test_citation_validation.py::test_judge_error_fails_closed`,
  `test_malformed_judge_output_fails_closed`, `test_omitted_pair_fails_closed`.
- Judge temperature is 0 for every judge call.
- The runtime claim verifier judges each (claim, cited chunk) pair
  independently; a chunk citation is verified only if EVERY claim citing it
  is supported.

## 4. Reproducibility

Every evaluation report (`evals/reports/*.json`) records: provider mode
(real/mock), dataset path + sha256, fixture corpus sha256, per-baseline
summaries, per-row metrics with unscored reasons, timestamps, and an
explicit limitations block. Re-running with the same corpus, dataset, and
provider mode reproduces the same numbers bit-for-bit under the mock
provider (deterministic embedder + deterministic mock LLM).

## 5. Calibration status

- Human-labeled calibration sample: **not available in this environment.**
  No agreement statistics are claimed. This is stated, not papered over.
- The dataset itself (50 golden rows) was authored against the synthetic
  fixture corpus; labels describe that corpus and are validated
  structurally (placeholder/unknown-id/duplicate/enum checks) by
  `evals/run.py:load_dataset` with regression tests in
  `tests/unit/test_eval_validation.py`.
- Pairwise candidate ordering and randomized order presentation are
  **not implemented** (single-system evaluation only); recorded as a
  follow-up if comparative model evaluation is ever needed.

## 6. Gates (CI, `make eval-smoke`)

Thresholds are tied to the measured fixed baseline with margins; they are
floors, not targets, and missing metrics FAIL the gate (never silently
skip):

| Metric | Gate | Measured (agentic, full golden, mock) |
|---|---|---|
| behavior_compliance | >= 0.90 | 0.959 |
| pattern_faithfulness | >= 0.60 | 0.686 |
| recall_at_k | >= 0.80 | 0.857 |
| unexpected_failure_rate | <= 0.05 | 0.041 |
| unauthorized_citations | == 0 | 0 |
| smoke latency | < 30s/query | p95 = 4ms |
| placeholder answers / missing metrics | FAIL | never (gate asserts presence) |

## 7. Known limitations (stated, not hidden)

- pattern_faithfulness is a deterministic extractive-grounding proxy, not a
  rubric score; under the mock provider the answer is produced by a
  deterministic extractive generator, so answer-quality numbers measure the
  retrieval stack through a fixed summarizer - useful for regression
  detection, not a claim about a production LLM.
- Rubric scores (0-4) require a real provider; blocked in this environment
  (no real API key). The nightly CI job evaluates with real providers when
  secrets exist.
- clarify behavior is not implemented; rows expecting it are marked
  unscored with reasons in the reports.
- fault-injection scenario rows (adversarial.jsonl, `harness:
  fault_injection`) are covered by the deterministic test suite
  (see test_matrix.md), not by judge scoring.
