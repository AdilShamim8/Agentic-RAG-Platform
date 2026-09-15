# Query Rewriting

> How this project transforms a raw user query into one or more optimized retrieval queries before hitting the document corpus.

## Concept

**Query rewriting** is the transformation of a user's natural-language query into a form (or multiple forms) that retrieves better results from the document corpus. The original query may be ambiguous, colloquial, under-specified, or refer to context only available in conversation history.

In this project, query rewriting is handled by the **Planner** agent step — it decomposes the original query into focused sub-questions, each of which becomes a targeted retrieval call.

## Why it exists

Users write queries the way they think, not the way documents are written:

| User query | Problem | Better retrieval query |
| ---------- | ------- | ---------------------- |
| "What's the deal with remote work?" | Colloquial; vague | "remote work policy current effective date" |
| "Summarize Q2 risks for Project X" | Multi-hop; requires decomposition | Sub-query 1: "Project X Q2 risk register"; Sub-query 2: "Project X Q2 incidents" |
| "What did we decide last week?" | Temporal; relative date | "decisions meeting 2025-01-06 to 2025-01-12" |
| "Is POL-2024-007 still current?" | Requires version lookup | "POL-2024-007 version history effective_to" |

Without query rewriting, a single embedding of the original query may miss the most relevant chunks, especially for multi-hop and temporal queries.

## How it works (in this project)

Query rewriting in this system occurs in two places:

### 1. Planner decomposition (primary)

The **Planner** (`src/agents/planner.py`) receives the classified query and decomposes it into a list of `(sub_question, tool, tool_args)` triples:

```
Input: "Summarize what changed in Project X during Q2 and identify the major risks."

Output (plan):
  Step 1: search_by_project(project="Project X", query="Q2 objectives", date_range=("2025-04-01", "2025-06-30"))
  Step 2: search_by_project(project="Project X", query="Q2 completed work", date_range=("2025-04-01", "2025-06-30"))
  Step 3: search_by_project(project="Project X", query="Q2 incidents issues blockers", date_range=("2025-04-01", "2025-06-30"))
  Step 4: search_by_project(project="Project X", query="current risk register")
```

Each sub-question is a targeted retrieval query. The tool and its arguments specify additional filters (date range, project, department) that narrow the search space before the vector/FTS search runs.

### 2. HyDE (Hypothetical Document Embedding) — optional

For simple factual queries, a hypothetical answer ("If the answer existed, what would the document say?") can be embedded instead of the raw question. This moves the query vector closer to the space of likely answers rather than the space of questions.

Example:
- Raw query: "What is the maternity leave policy?"
- Hypothetical document: "The maternity leave policy allows employees to take up to 16 weeks of paid leave following the birth or adoption of a child..."

The hypothetical document's embedding is used for dense retrieval. This technique is not the primary path in this system — the planner decomposition is — but it is a known improvement and could be added to `src/retrieval/engine.py` as a pre-retrieval step.

### 3. Conversation context injection

When a query references previous conversation turns ("what about the second point?"), the agent prepends the relevant conversation history to the query before planning. This is handled in the orchestrator: the last N messages are included in the planner's context so it can resolve anaphora.

## Where it appears in the code

| File | Purpose |
| ---- | ------- |
| `src/agents/planner.py` | Query decomposition into sub-questions |
| `src/agents/orchestrator.py` | Injects conversation history into planner context |
| `prompts/v1/planning.md` | Prompt that instructs the LLM to decompose the query |
| `src/agents/tools/` | Tool definitions that accept the rewritten sub-queries |
| `src/retrieval/engine.py` | Entry point for retrieval; receives sub-queries from tools |

## Trade-offs

### Decomposition vs. single-shot retrieval

| Approach | Pros | Cons |
| -------- | ---- | ---- |
| Single retrieval (pipeline RAG) | Fast (1 LLM call saved) | Misses multi-hop queries |
| Planner decomposition (this project) | Handles complex queries | 1 extra LLM call for planning (~200ms, ~$0.0001) |

For our query mix (~40% simple, ~30% multi-hop), decomposition is worth the cost. For a pure FAQ bot, it would not be.

### LLM planner vs. rule-based decomposition

- **LLM planner** (this project): flexible; handles novel query types; can fail with bad prompts.
- **Rule-based**: deterministic; faster; limited to known query patterns.

We use an LLM planner (see ADR-004) because the query space is too diverse for rules to cover reliably.

### HyDE vs. direct embedding

- **HyDE**: better recall on factual queries; adds 1 LLM call; not implemented in this project's primary path.
- **Direct embedding**: simpler; already improved by the reranker cross-encoder.

The reranker already compensates for much of the embedding quality gap, making HyDE a lower-priority improvement.

## Failure modes

| Failure | Description | Mitigation |
| ------- | ----------- | ---------- |
| Planner generates too many sub-questions | Token budget overflow; slow | `max_tool_calls=10` hard limit |
| Planner generates irrelevant sub-questions | Bad retrieval; wrong answer | Planner prompt refinement; eval regression test |
| Planner ignores conversation context | Fails to resolve "what about the second point?" | Include last N messages in planner context |
| `AGENT_LOOP` | Same sub-question generated twice | Loop detector (`AgentState.is_looping()`) |

See `docs/operations/runbook.md` for the `AGENT_LOOP` runbook.

## Experiment results

See `evals/reports/comparison.md` — compare Baseline 4 (hybrid, no agent, no decomposition) vs. Baseline 6 (full agentic with decomposition). The improvement in Recall@5 for multi-hop queries is the key signal. **Replace placeholders with real measurements.**

## Further reading

- Ma et al., "Query Rewriting for Retrieval-Augmented Large Language Models" (2023) — systematic study of query rewriting strategies for RAG.
- Gao et al., "Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)" (2022) — the HyDE paper.
- Asai et al., "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection" (2023) — self-reflective retrieval with query adaptation.
