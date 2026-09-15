# Threat Model & STRIDE Analysis — Agentic RAG Platform

> Comprehensive threat assessment applying the Microsoft STRIDE methodology across platform assets, external entrypoints, and generative AI execution boundaries.

---

## 1. Asset Inventory & Classification

1. **Retrieved Chunks**: Proprietary enterprise documents and chunk vectors containing sensitive internal policies, financials, and technical IP.
2. **User Memory**: Ephemeral and long-term user preferences, project contexts, and query history.
3. **LLM Prompts & System Persona**: System instructions, safety guards, and tool definitions.
4. **Tool Invocations & Arguments**: Agentic function calls executing retrievals and database lookups.
5. **API Surface**: Ingress REST endpoints (`/query`, `/documents`, `/memory`, `/admin`).
6. **Vector & Relational Storage**: PostgreSQL database containing `pgvector` embeddings, user records, and role grants.
7. **Audit Logs**: Immutable ledger of administrative and security events.
8. **Telemetry & Traces**: OpenTelemetry distributed spans and Langfuse execution graphs.

---

## 2. Comprehensive STRIDE Matrix

### 2.1. Spoofing Identity

| Threat Scenario | Impact | Primary Mitigation Layer | Residual Risk |
| :--- | :--- | :--- | :--- |
| **User Identity Spoofing** | Attacker impersonates legitimate user to access private data | JWT signed with HMAC-SHA256 (`JWT_SECRET` >= 64 chars); short expiration (60m); signature verified on every request | Negligible assuming secure secret storage |
| **API Impersonation (MITM)** | Attacker intercepts transit traffic | TLS 1.3 encryption enforced at ingress; HSTS headers | Zero on public network |
| **Upstream LLM Provider Spoofing** | Malicious response injected as LLM completion | Strict TLS validation of provider HTTPS endpoints with certificate pinning | Zero |

---

### 2.2. Tampering with Data

| Threat Scenario | Impact | Primary Mitigation Layer | Residual Risk |
| :--- | :--- | :--- | :--- |
| **Chunk / Document Poisoning** | Ingestion of malicious documents to mislead agent responses | Ingestion restricted to `manager`/`administrator` roles; SHA-256 deduplication and validation | Insider threat with ingest capability |
| **Audit Log Tampering** | Attacker attempts to delete or alter audit entries | Append-only database table; nightly off-site replication to immutable S3 object storage | Managed DB admin access |
| **Prompt Tampering** | Unauthorized modifications to system prompts | Prompt templates version-controlled in git; runtime files read-only | Host filesystem compromise |
| **Tool Argument Manipulation** | Model produces corrupted or malicious arguments | Pydantic JSON-schema validation in `execute_tool()`; strict range bounds | Pydantic schema bugs |

---

### 2.3. Repudiation

| Threat Scenario | Impact | Primary Mitigation Layer | Residual Risk |
| :--- | :--- | :--- | :--- |
| **Query Disavowal** | User claims they did not execute a sensitive search | Distributed tracing associates cryptographic `user_id`, IP, and `trace_id` with every query | Trace retention expiration |
| **Administrative Repudiation** | Admin denies deleting documents or modifying roles | All privileged operations synchronously written to `audit_logs` table before execution | DB administrator root access |

---

### 2.4. Information Disclosure

| Threat Scenario | Impact | Primary Mitigation Layer | Residual Risk |
| :--- | :--- | :--- | :--- |
| **Unauthorized Chunk Retrieval** | Employee accesses confidential executive documents | Pre-retrieval SQL filtering via `rag.access_matches()` in the `WHERE` clause prior to vector search | Zero RBAC leakage observed |
| **Cross-User Memory Leakage** | User A retrieves personal preferences or memories of User B | Strict SQL filter `WHERE user_id = :user_id` enforced in memory repository | Zero |
| **System Prompt Extraction** | Adversary attempts to leak system instructions | Input classifier blocks extraction attempts; output sanitizer detects leaked prompt tokens | Obfuscated token steganography |
| **Secret Leakage in Logs** | API tokens or keys output to logging streams | Structlog redaction processor masks API keys, bearer tokens, passwords, and PII | Unforeseen secret formats |
| **PII Exposure in Telemetry** | User queries containing SSNs or emails saved to traces | PII regex scrubbing; telemetry records `query_hash = sha256(query)` instead of raw text | None |

---

### 2.5. Denial of Service (DoS)

| Threat Scenario | Impact | Primary Mitigation Layer | Residual Risk |
| :--- | :--- | :--- | :--- |
| **Agent Infinite Execution Loop** | Cyclical tool calls drain API budget and CPU | Hard limits (`max_steps=8`, `max_tool_calls=10`, `timeout=30s`); loop detection via `(tool, args_hash)` | None (100% deterministic termination) |
| **Payload Size Exhaustion** | 50MB malicious query string exhausts RAM | Pydantic request model caps input query length at 2,000 characters (returns HTTP 422) | None |
| **Query Flood / Traffic Spikes** | Influx of queries overwhelms database and LLM quota | Ingress reverse-proxy rate limiting (Nginx / Cloudflare 100 req/min per IP); DB connection pool limits | Distributed botnets bypassing IP rate limits |
| **Corrupted File Ingestion Bomb** | Infinite decompression or parser crash | Ingestion loader validates MIME magic bytes and enforces 50MB file size limits | CPU spike on massive valid PDFs |
| **Candidate Fan-out Explosion** | Model requests unbounded retrieval candidates | Hard ceiling on retrieval top-K (`top_k <= 50`) enforced at database query layer | None |

---

### 2.6. Elevation of Privilege

| Threat Scenario | Impact | Primary Mitigation Layer | Residual Risk |
| :--- | :--- | :--- | :--- |
| **Role Claim Injection in Body** | Attacker includes `"role": "admin"` in JSON request body | Roles read strictly from verified JWT claims, never accepted from user-supplied payloads | None |
| **Indirect Prompt Injection** | Untrusted document contains instructions to bypass safety | Chunks enclosed in `<retrieved_document>` XML tags; output sanitizer scans completions | Highly complex reasoning jailbreaks |
| **Tool Capability Escape** | Model executes unapproved system commands | Strict whitelist of permitted tool call handlers in Orchestrator; no shell execution | None |

---

## 3. Attack Surface Map

```
Internet / Untrusted Clients
         │
         ▼
┌───────────────────────────────┐
│ Ingress Rate Limiter & TLS    │  <-- Blocks flood attacks & MITM
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ FastAPI Application Gateway   │  <-- JWT validation & Pydantic schema validation
└──────────────┬────────────────┘
               │
         ┌─────┴─────────────────────────────┐
         ▼                                   ▼
┌──────────────────┐               ┌──────────────────┐
│ /query Endpoint  │               │ /documents Ingest│
│ (Input Classifier│               │ (Role: Admin)    │
│  & XML Isolation)│               └──────────────────┘
└────────┬─────────┘
         │
         ▼
┌────────────────────────────────┐
│ Pre-Retrieval SQL RBAC Engine  │  <-- Zero unauthorized chunks retrieved
│ (rag.access_matches)           │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│ LLM Synthesis & Output Filter  │  <-- Output sanitizer blocks leakage
└────────────────────────────────┘
```

---

## 4. Residual Risks & Future Hardening

1. **Model Compliance with Context Boundaries**: While `<retrieved_document>` XML tags isolate passive data, novel multi-hop jailbreaks remain an active industry-wide research topic. Mitigated by continuous adversarial benchmarking.
2. **Distributed Per-User Rate Limiting**: Edge proxies enforce per-IP rate limits; distributed Redis sliding-window token buckets per authenticated `user_id` are scheduled for the next major release.
3. **Database Administrator Isolation**: Database superusers have direct access to chunk tables; encryption-at-rest (pgcrypto / AWS KMS) and external immutable audit log streaming to S3 mitigate insider threats.

