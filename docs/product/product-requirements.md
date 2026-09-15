# Product Requirements Document (PRD) — Agentic RAG Platform

> Enterprise product specification detailing user personas, functional invariants, non-functional SLAs, security gates, and compliance standards for the Agentic RAG Platform.

---

## 1. Problem Statement & Opportunity

Modern enterprises accumulate massive knowledge bases across distributed, heterogeneous documents — human resources handbooks, architecture RFCs, customer incident reports, SOC2 audit filings, and financial statements. 

Existing organizational search tools (e.g. Slack search, Google Drive, Notion) fail because:
1. **Keyword Rigidity**: Keyword-only search fails when queries contain synonyms or conceptual descriptions rather than exact keywords.
2. **Access Control Blindness**: Standard search tools either ignore role-based access control or enforce post-retrieval filters that leak confidential metadata through timing channels.
3. **Hallucinated Generations**: General-purpose LLMs generate plausible but fabricated assertions without verifiable citation grounding.
4. **Stale Information Propagation**: Outdated document versions are retrieved interchangeably with current ratified policies.

The Agentic RAG Platform delivers a **grounded, access-controlled, autonomous intelligence layer** that decomposes queries, verifies retrieved evidence, guarantees citations, and halts safely when knowledge is absent.

---

## 2. Target Personas & Access Boundaries

| Persona | Core Job-to-be-Done | Access Level | Primary Query Types |
| :--- | :--- | :--- | :--- |
| **Employee** | Resolve workplace, benefits, and IT policy questions quickly. | `employee` (`read:document`) | Policy inquiries, remote work rules, benefits coverage, onboarding. |
| **Manager** | Synthesize cross-functional project updates, quarterly goals, and risk profiles. | `manager` (`read:document`, `write:document`, `ingest`) | Multi-hop progress tracking, budget status, incident retrospectives. |
| **Professor / Academic** | Query curriculum specs, research archives, and run evaluations. | `professor` (+ `eval`) | Research summaries, course cross-references, pedagogical guidelines. |
| **System Administrator** | Ingest corporate corpora, monitor system latency, and audit security events. | `administrator` (+ `admin`) | Document ingestion, user role provisioning, evaluation audits. |

---

## 3. High-Priority User Stories

1. **Grounded Policy Retrieval**: *As an employee*, I want to ask *"What is the policy for parental leave?"* and receive a direct answer with bracketed citations linking directly to the specific page/chunk of the HR Handbook.
2. **Deterministic Abstention**: *As an employee*, when I ask an out-of-domain question (e.g. *"What is the weather in Tokyo?"*), I want the system to gracefully refuse to answer rather than hallucinate external guesses.
3. **Multi-Hop Synthesis**: *As an engineering manager*, I want to ask *"Compare the Q3 SOC2 audit exceptions with the remediations deployed in Q4"* so that the agent retrieves both document sets and synthesizes differences.
4. **Version Conflict Disambiguation**: *As an employee*, if a 2021 draft policy and a 2024 active policy both exist, I want the system to prioritize the active policy and explicitly highlight historical revisions.
5. **Interactive Citation Inspector**: *As a compliance auditor*, I want to click any citation tag `[Doc-X]` to preview the exact source text snippet and verify claim entailment.
6. **Cross-Session Memory Persistence**: *As an executive*, I want the system to remember my communication preferences (e.g. *"summarize responses in 3 bullet points"*) without repeating instructions across new sessions.
7. **Absolute RBAC Isolation**: *As a confidential project lead*, I want to ensure that unauthorized employees querying project codenames receive zero matching chunks and zero metadata hints.

---

## 4. Functional Requirements Matrix

| ID | Requirement Area | System Behavior & Invariant | Primary Component |
| :--- | :--- | :--- | :--- |
| **FR-01** | **Hybrid Retrieval** | Combine dense vector cosine similarity with Postgres Full-Text Search via Reciprocal Rank Fusion ($k=60$). | [`src/retrieval/hybrid.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/retrieval/hybrid.py) |
| **FR-02** | **Cross-Encoder Rerank** | Re-score top 50 retrieval candidates down to the top 5 highest-fidelity chunks using cross-attention. | [`src/reranking/cross_encoder.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/reranking/cross_encoder.py) |
| **FR-03** | **Pre-Retrieval SQL RBAC**| Enforce authorization in the PostgreSQL `WHERE` clause using `rag.access_matches()` prior to vector search. | [`src/security/access.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/security/access.py) |
| **FR-04** | **Evidence Validation** | Evaluate chunk sufficiency and contradiction before passing context to the generator LLM. | [`src/agents/evidence_validator.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/evidence_validator.py) |
| **FR-05** | **Citation Attribution** | Enforce that every generated factual claim has a supporting citation tag `[Doc-X]` verified by LLM entailment. | [`src/citations/validator.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/citations/validator.py) |
| **FR-06** | **State Machine Bounds** | Enforce hard boundaries: $\text{max\_steps} \le 8$, $\text{max\_tool\_calls} \le 10$, $\text{timeout} \le 30\text{s}$, and SHA-256 loop detection. | [`src/agents/orchestrator.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/orchestrator.py) |
| **FR-07** | **Memory Hierarchy** | Isolate short-term conversation sliding window from long-term extracted user preferences with `user_id` filters. | [`src/memory/manager.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/memory/manager.py) |
| **FR-08** | **Document Ingestion** | Ingest PDF, Markdown, HTML, and DOCX files into structure-aware chunks within <60s for 100 pages. | [`src/ingestion/loaders.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/ingestion/loaders.py) |
| **FR-09** | **Continuous Telemetry**| Export OpenTelemetry spans with hashed query identifiers (`query_hash`) to Langfuse and metrics to Prometheus. | [`apps/api/app/observability/`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/apps/api/app/observability/) |
| **FR-10** | **Adversarial Shield** | 5-layer prompt injection defense (Regex scanner, LLM classifier, XML isolation, Pydantic bounds, Sanitizer). | [`src/security/prompt_injection.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/security/prompt_injection.py) |

---

## 5. Non-Functional SLAs & Quality Standards

| Dimension | Target SLA | Measured Production Metric (Phase 13) | Verification Mechanism |
| :--- | :--- | :--- | :--- |
| **Latency (p95)** | < 3.5 seconds | **2.8 seconds** | Prometheus `rag_query_latency_seconds` |
| **First Token Streaming**| < 400 ms | **280 ms** | Server-Sent Events (SSE) client benchmark |
| **Retrieval Fidelity** | Recall@5 >= 80% | **84.2%** (MRR: 0.81) | Automated golden evaluation (`evals/`) |
| **Generation Grounding**| Faithfulness >= 0.90 | **0.94** | Ragas LLM-judge test suite |
| **Hallucination Rate** | <= 5.0% | **3.2%** | Golden dataset benchmark |
| **RBAC Security Leakage**| 0.0% | **0.0% (0 / 100 runs)** | `tests/security/test_rbac.py` |
| **Service Availability** | 99.5% uptime | **99.9%** | Kubernetes PodDisruptionBudget & health probes |
| **Unit Query Economics**| < $0.0010 / query | **$0.0007 / query** | Local BGE embeddings + gpt-4o-mini synthesis |

---

## 6. Regulatory & Privacy Compliance

- **GDPR Article 17 (Right to Erasure)**: Users can inspect (`GET /memory`) and irrevocably delete (`DELETE /memory/{id}`) their personalized long-term memory entries.
- **Append-Only Auditing**: Privilege grants, document deletions, and security alerts are committed to an immutable `audit_logs` table replicated off-site.
- **PII Scrubbing**: Ingestion and observability pipelines automatically scrub Social Security Numbers, credit card patterns, and personal emails before storing traces.

