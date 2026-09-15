# Agentic Reasoning and LLM Architecture Principles

Authored by: Andrej Karpathy (@karpathy)
Reviewed by: Adil Shamim (@AdilShamim8)

## 1. System 1 vs. System 2 in Agentic RAG
Modern Agentic RAG platforms bridge the gap between fast pattern matching (System 1) and deliberative, iterative reasoning (System 2):
- **Iterative Retrieval**: Instead of a single retrieval shot, agents formulate sub-queries, inspect candidate evidence, and backtrack if the evidence is insufficient or contradictory.
- **Thinking and Tool Use**: Decouple the reasoning loop from external tool execution. Always preserve intermediate tool observations in the conversation context without leaking internal scratchpads to the end user.

## 2. Hallucination Mitigation & Citation Verification
- Ground every factual claim directly to an immutable document chunk via exact span offsets or semantic validation.
- Maintain pre-retrieval role-based access control (RBAC) at the database layer (PostgreSQL Row-Level Security and filter parameters) rather than filtering after vector retrieval.

## 3. Evaluation-Driven Iteration
- Establish strict golden datasets with automated faithfulness and hallucination rate quality gates in CI/CD pipelines.
- Continuous evaluation prevents prompt regression and preserves high retrieval precision across diverse document types.
