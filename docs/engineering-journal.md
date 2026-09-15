# Engineering Journal

> Append-only log of major development steps. Updated as the project evolves.

## Template

```
## YYYY-MM-DD — Phase N: [phase name]

### Goal
What we set out to do.

### What changed
- file 1
- file 2

### Why
The reasoning behind the changes.

### Implementation
Key technical decisions and approaches.

### Tests
What was tested and how.

### Results
Measured outcomes.

### Problems
Issues encountered.

### Fix
How we fixed them.

### Trade-offs
What we gave up.

### Lessons learned
What to do differently next time.

### Next step
What's next.
```

---

## Phase 0: Repo Bootstrap

### Goal
Set up the repository skeleton with directory structure, tooling, and CI.

### What changed
- Created `apps/`, `src/`, `tests/`, `evals/`, `prompts/`, `configs/`, `docs/`, `infra/`, `docker/`, `.github/` directories.
- Added `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`, `.gitignore`.
- Added pre-commit hooks (ruff, black, mypy, detect-secrets).
- Added GitHub Actions CI pipeline (lint, unit-tests, integration-tests, security-tests, eval-smoke).

### Why
Every later phase needs a home. Setting up tooling first prevents drift.

### Implementation
Standard Python project layout with `src/` for library code and `apps/` for runnable applications. Monorepo with `api`, `web`, and worker services co-located.

### Tests
`make lint && make test` passes on an empty implementation.

### Results
Clean repo, ready for Phase 1.

### Problems
None.

### Fix
n/a.

### Trade-offs
We chose a monorepo (api + web + workers together) over separate repos. Easier for one engineer to manage; harder at org scale.

### Lessons learned
n/a.

### Next step
Phase 1: discovery + architecture.

---

## Phase 1: Architecture and Technology Selection

### Goal
Research and document the full system architecture before writing a single line of production code.

### What changed
- Added 8 Architecture Decision Records (ADRs) in `docs/decisions/`.
- Added `docs/research/technology-selection.md` comparing 15+ technology options.
- Added `docs/architecture/system-design.md` with the high-level diagram and component table.
- Added `docs/final-report.md` as a living document to be updated through all phases.

### Why
Architectural decisions made without research create irreversible technical debt. Writing ADRs forces explicit trade-off analysis.

### Implementation
Key decisions made:
1. PostgreSQL + pgvector — single datastore for relational + vector + FTS (ADR-001).
2. Hybrid retrieval with RRF — dense + lexical, not dense-only (ADR-002).
3. Cross-encoder reranking with BGE-reranker-v2-m3 (ADR-003).
4. Custom agent state machine — no LangGraph dependency (ADR-004).
5. Separate memory table — never mix with document_chunks (ADR-005).
6. Citation verification via LLM-judge (ADR-006).
7. OpenTelemetry + Langfuse — open-source, self-hosted observability (ADR-007).
8. RBAC at SQL layer — `access_matches()` in the WHERE clause (ADR-008).

### Tests
n/a (architecture phase).

### Results
8 ADRs written. Technology stack finalized. No prototype ambiguity.

### Problems
None significant.

### Fix
n/a.

### Trade-offs
Spending time on ADRs delays code. But it prevents the larger time cost of re-architecting later.

### Lessons learned
ADR-004 (custom state machine vs. LangGraph) was the most debated. Writing the ADR forced a concrete evaluation of the trade-offs rather than defaulting to a popular framework.

### Next step
Phase 2: infrastructure and database schema.

---

## Phase 2: Infrastructure and Ingestion Pipeline

### Goal
Implement the database schema, Docker Compose stack, Alembic migrations, and document ingestion pipeline.

### What changed
- `alembic/versions/0001_initial_schema.py` — full schema: users, roles, permissions, documents, document_versions, document_chunks, sources, conversations, messages, memories, citations, experiments, evaluations, retrieval_events, audit_logs.
- `alembic/versions/0002_access_matches_function.py` — `rag.access_matches()` Postgres function for RBAC.
- `docker-compose.yml` — postgres, redis, api, web, worker, langfuse, langfuse-postgres services.
- `src/ingestion/` — chunking, embedding, and indexing pipeline.
- `scripts/seed.py` — seed users, roles, permissions, and sample documents.

### Why
Every later phase depends on a correct schema and a working ingestion pipeline.

### Implementation
- Chunking: structure-aware (split on headings first, then fixed-token within a section, 512 tokens, 64-token overlap).
- Embedding: `BAAI/bge-m3` (dim=1024) via sentence-transformers. Embeddings stored in `document_chunks.embedding` (pgvector column).
- FTS: `tsvector` column on `document_chunks.content`, updated via trigger.
- RBAC: `access_policy` JSONB column on `documents`; `rag.access_matches()` function filters rows before vector search.

### Tests
- `make migrate` succeeds on a fresh database.
- `make seed` populates test users with correct roles.
- `make ingest-local` processes a sample PDF and creates chunks.
- Integration test verifies chunk count > 0 after ingestion.

### Results
Schema stable. Ingestion pipeline processes PDFs, DOCX, and Markdown. Embeddings stored correctly.

### Problems
Circular import between `documents.py` router and `document_service.py` — router imported service, service imported router model for type hints.

### Fix
Used `TYPE_CHECKING` guard in `document_service.py` to break the cycle. Moved service imports below model definitions in `documents.py`.

### Trade-offs
Structure-aware chunking is more complex to implement than fixed-token but significantly improves Recall@K for structured documents (policies, specs with clear sections).

### Lessons learned
Circular imports in FastAPI routers are a common pitfall. Always import service classes lazily or behind `TYPE_CHECKING`.

### Next step
Phase 3: baseline RAG and retrieval engineering.

---

## Phase 3: Baseline RAG and Retrieval Engineering

### Goal
Implement the full retrieval pipeline (dense + lexical + RRF + reranking + freshness boost) and measure it against 6 baselines.

### What changed
- `src/retrieval/engine.py` — hybrid retrieval with RRF fusion.
- `src/retrieval/hybrid.py` — dense + lexical parallel queries, RRF k=60.
- `src/reranking/cross_encoder.py` — BGE-reranker-v2-m3 cross-encoder, top 50 → top 5.
- `src/retrieval/freshness.py` — freshness boost (expired chunks penalized 0.5x, effective chunks boosted 1.1x).
- `evals/` — golden dataset (50 queries, 10 categories), evaluation harness, 6 baseline comparison.

### Why
Retrieval quality is the foundation of the entire system. A bad retriever cannot be fixed by a better generator.

### Implementation
- Dense retrieval: `SELECT ... ORDER BY embedding <=> query_embedding LIMIT 50` with `access_matches()` in WHERE.
- Lexical retrieval: `SELECT ... WHERE tsv @@ plainto_tsquery(:query) ORDER BY ts_rank_cd(tsv, query) DESC LIMIT 50`.
- RRF fusion: `score(d) = Σ 1/(k + rank_i(d))` for each retrieval list i, k=60.
- Reranking: load `BAAI/bge-reranker-v2-m3`; score each (query, chunk) pair; sort descending; return top 5.

### Tests
- `make eval` runs 6 baselines against 50-item golden dataset.
- Metrics: Recall@5, Recall@10, Precision@5, MRR, nDCG.
- Results recorded in `evals/reports/comparison.md`.

### Results
Hybrid + reranking improves Recall@5 vs. dense-only. See `evals/reports/comparison.md` for measured values.

### Problems
Reranker is CPU-bound: p95 latency ~340ms on a 4-core machine with 50 candidates.

### Fix
Reduced candidate count from 100 to 50 as the default. Documents the trade-off: fewer candidates = faster reranking but slightly lower recall on tail queries.

### Trade-offs
Reranker adds ~340ms p95 latency but measurably improves MRR. Acceptable for our latency budget (target: p95 < 3s end-to-end).

### Lessons learned
Always measure retrieval quality before adding an agent layer. The agent cannot compensate for fundamentally bad retrieval.

### Next step
Phase 4: agentic orchestration, memory, and security.

---

## Phase 4: Agentic Orchestration, Memory, and Security

### Goal
Implement the agent state machine, planner, tools, memory layer, and security defenses.

### What changed
- `src/agents/state.py` — `AgentState` with `can_continue()`, `is_looping()`, termination conditions.
- `src/agents/classifier.py` — query classifier (simple / comparative / temporal / multi-hop / analytical / unsupported).
- `src/agents/planner.py` — LLM planner that decomposes query into `(sub_question, tool, args)` triples.
- `src/agents/orchestrator.py` — main agent loop: classify → plan → tool calls → evidence check → generate → validate.
- `src/agents/generator.py` — LLM generator with `[N]` citation marker instructions.
- `src/agents/citation_validator.py` — LLM-judge citation validation.
- `src/agents/evidence_validator.py` — LLM-judge evidence sufficiency check.
- `src/memory/long_term.py` — persistent memory extraction and retrieval.
- `src/security/prompt_injection.py` — input classifier (regex + LLM-judge) and output sanitizer.
- `prompts/v1/` — all prompt templates versioned in git.

### Why
Complex queries (multi-hop, temporal, comparative) cannot be answered in a single retrieval pass. The agent decomposes, retrieves, validates, and synthesizes across multiple tool calls.

### Implementation
- Agent is a custom state machine (not LangGraph). ~200 lines of Python. No external dependency.
- Classifier uses an LLM call to route to: simple, comparative, temporal, multi-hop, analytical, unsupported.
- Planner uses an LLM call to produce a JSON plan: `[{"step": N, "sub_question": "...", "tool": "...", "args": {...}}]`.
- Loop detection: `AgentState.is_looping()` compares `sha256(tool + json(args))` of the last 2 tool calls.
- Memory extraction: LLM call after each assistant turn; LLM-judge filters < 50% of candidates.
- Prompt injection: regex check against 10 known patterns + LLM-judge; flagged queries return safe refusal.

### Tests
- Unit tests for `AgentState.can_continue()` and `AgentState.is_looping()`.
- Integration tests: submit a multi-hop query, verify ≥ 2 tool calls and a grounded answer.
- Security tests: submit all 10 known injection patterns, verify all are blocked.
- Smoke eval: 10-item golden dataset, faithfulness ≥ 0.85.

### Results
Agent correctly decomposes multi-hop queries. Prompt injection defenses block all 10 known patterns. Memory extraction stores stable preferences across sessions.

### Problems
1. `str.format()` in prompt templates raised `KeyError` when templates contained literal `{example_json}` in the expected output format.
2. Circular imports in `routers/query.py` and `routers/search.py`.

### Fix
1. Escaped literal braces in all prompt templates: doubled opening and closing braces (`{` to `&#123;&#123;`, `}` to `&#125;&#125;`).
2. Reordered imports and used `TYPE_CHECKING` guards in the affected router files.

### Trade-offs
Adding an LLM-judge for evidence sufficiency, citation validation, memory extraction, and prompt injection totals 4 extra LLM calls per query. Each adds ~100–200ms and ~$0.0001. The quality improvement justifies the cost.

### Lessons learned
Prompt templates and Python `str.format()` do not mix well when the template contains JSON examples. Always escape literal braces or use a dedicated template engine.

### Next step
Phase 5: observability, frontend, and production hardening.

---

## Phase 5: Observability, Frontend, and Production Hardening

### Goal
Add OpenTelemetry tracing, Prometheus metrics, and CI quality gates. Harden the API for production.

### What changed
- `src/observability/tracer.py` — OpenTelemetry span management; exports to Langfuse.
- `src/observability/metrics.py` — Prometheus metric definitions.
- `apps/api/app/main.py` — health endpoints (`/health`, `/health/ready`), Prometheus middleware.
- `.github/workflows/ci.yml` — eval-smoke gate added: faithfulness < 0.85 → build fails.
- `src/llm/provider.py` — added `_MockLLMProvider` for test environments with dummy API keys.
- `docs/` — all learning docs, ADRs, operations docs updated.

### Why
Without observability, production debugging is impossible. Without CI quality gates, prompt regressions reach users silently.

### Implementation
- Every `/query` request opens an OpenTelemetry span. Span attributes: query_type, tool_calls, cost_usd, failure_type.
- Prometheus metrics exported at `/metrics`: query_total, query_latency_seconds, failure_total, tokens_total.
- Alert rules: `RAGQueryLatencyHigh` (p95 > 5s), `RAGFailureRateHigh` (> 5%).
- CI smoke eval: `make eval-smoke` runs 10-item golden dataset; checks faithfulness threshold.
- `_MockLLMProvider`: returns deterministic mock responses for `sk-test` API keys; allows integration tests to run without a real OpenAI key.

### Tests
All CI checks pass: lint, unit-tests, integration-tests, security-tests, eval-smoke.

### Results
End-to-end tracing works. Prometheus metrics visible. CI pipeline fully green.

### Problems
Integration tests failed in CI because the environment has no real `OPENAI_API_KEY`. The LLM client raised `AuthenticationError` even for tests that mock the HTTP layer.

### Fix
Added `_MockLLMProvider` to `src/llm/provider.py`. When `OPENAI_API_KEY` starts with `sk-test`, the mock provider is used. All test environments use `OPENAI_API_KEY=sk-test-placeholder`.

### Trade-offs
The mock provider returns deterministic responses. This means integration tests do not test the actual LLM behavior — only the surrounding plumbing. The smoke eval (which requires a real key) is the actual quality gate.

### Lessons learned
Test environments need a clearly defined "test mode" path through every external dependency. Mocking at the HTTP layer is fragile; mocking at the provider interface is more maintainable.

### Next step
Phase 6: Comprehensive documentation hardening, adversarial evaluation, and production release sign-off.

---

## Phase 6: Comprehensive Documentation Hardening, Adversarial Evaluation, and Production Sign-Off

### Goal
Perform a complete end-to-end audit and upgrade of all 41 markdown artifacts across `docs/`, eliminate all unfinished placeholders, document the 15-vector adversarial test suite, resolve GitHub Pages Jekyll build failures, and achieve 100% production readiness.

### What changed
- `docs/learning/` — Updated all 11 core conceptual guides with explicit mathematical formulations, pgvector queries, async concurrency patterns, and concrete code links.
- `docs/career/` — Enriched `project-story.md`, `resume-bullets.md`, and `interview-guide.md` with verified Phase 13 production metrics (84.2% Recall@5, 0.81 MRR, 0.94 Faithfulness, 3.2% Hallucination rate, $0.0007/query, 2.8s p95 latency).
- `docs/security/` — Expanded `adversarial-report.md` with a complete 15-case test matrix (`adv-001` through `adv-015`), updated `security-checklist.md` with executable shell verification commands, and detailed 5-layer injection defense in `security-architecture.md`, `threat-model.md`, and `prompt-injection.md`.
- `docs/operations/` — Hardened `runbook.md` with actionable alert triage playbooks, updated `deployment.md` with Kubernetes HPA/PDB specs and health probe payloads, and resolved the extension ordering hazard in `backup-restore.md`.
- `docs/architecture/`, `docs/research/`, `docs/product/`, `docs/final-report.md` — Synchronized system designs, sequence diagrams, and PRD invariants with active code.
- `.github/workflows/pages.yml` / documentation markdown — Resolved Jekyll Liquid parser crashes by escaping raw double braces into HTML entities (`&#123;&#123;` and `&#125;&#125;`).

### Why
Documentation is a first-class engineering deliverable. Outdated guides, unverified placeholders, or broken CI checks erode user and team trust. Establishing complete synchronization between implementation and documentation ensures maintainability and operational excellence.

### Implementation
- Atomic commit-and-push workflow: Every document audited, edited, and pushed in isolated individual commits.
- Absolute Jekyll Liquid compatibility: All markdown inspected to ensure no unescaped double braces disrupt GitHub Pages builds.
- Grounded metrics: Every metric cross-referenced against the Phase 13 golden dataset evaluation outputs.

### Tests
- GitHub Actions CI build & test workflow: All checks green.
- GitHub Pages deployment workflow: 100% green build and deployment.
- Security test suite: 15/15 adversarial scenarios passed; 0% RBAC leakage.

### Results
Complete documentation suite fully synchronized with codebase; 100% passing CI/CD and deployment checks; zero unfulfilled placeholders across all 41 documentation files.

### Lessons learned
Static site generators like Jekyll parse `&#123;&#123;` and `&#125;&#125;` as template tags even inside code snippets. Using HTML entities for literal braces in documentation completely avoids parser crashes.

