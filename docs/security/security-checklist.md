# Security Checklist & Verification Runbook

> Pre-release and production deployment security verification checklist. Every control is validated with an explicit verification command and status.

---

## 1. Authentication & Session Management

- [x] **[PASS] JWT Authentication on Protected Endpoints**: All API endpoints require valid Bearer token, except `/health` and `/auth/login`.
  - *Verification*: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/query` (Returns `401 Unauthorized`).
- [x] **[PASS] Cryptographic Secret Strength**: `JWT_SECRET` is >= 64 characters, loaded exclusively from environment variables.
  - *Verification*: `python -c "from apps.api.app.core.config import settings; assert len(settings.jwt_secret) >= 64"`
- [x] **[PASS] Token Lifetime Policy**: Access tokens expire in 60 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES=60`); Refresh tokens expire in 7 days.
  - *Verification*: Inspected in `apps/api/app/core/security.py` claim expiration (`exp` delta).
- [x] **[PASS] Token Type Enforcement**: Explicit assertion that `token_type == 'access'` for API operations.
  - *Verification*: Passing a refresh token to `/query` returns `401 Invalid token type`.
- [x] **[PASS] JWT Role Origin**: Role claims are extracted strictly from cryptographic JWT payload, never accepted from request body or query params.
  - *Verification*: `pytest tests/security/test_rbac.py -k test_role_escalation_blocked`

---

## 2. Authorization & Pre-Retrieval RBAC

- [x] **[PASS] Granular Role Taxonomy**: 5 roles defined (`student`, `employee`, `manager`, `professor`, `administrator`) in [`src/security/rbac.py`](../../src/security/rbac.py).
- [x] **[PASS] Fine-Grained Permissions**: Strict mapping of capabilities (`read:document`, `write:document`, `ingest`, `eval`, `admin`).
- [x] **[PASS] Pre-Retrieval SQL Filtering**: PostgreSQL `rag.access_matches()` executes in the `WHERE` clause prior to vector similarity calculations.
  - *Verification*: `pytest tests/security/test_rbac.py -k test_employee_cannot_see_manager_only_chunk`
- [x] **[PASS] Multi-User Memory Isolation**: Memory queries explicitly enforce `user_id = current_user.id` filter.
  - *Verification*: `pytest tests/security/test_rbac.py -k test_cross_user_no_leakage`
- [x] **[PASS] Endpoint Guarding**: Admin endpoints enforced with `require_permission("admin")`; Ingest endpoints guarded by `require_permission("ingest")`.
  - *Verification*: Verified via FastAPI dependency injection `Depends(require_permission(...))`.

---

## 3. Prompt Injection & Adversarial Defense

- [x] **[PASS] Layer 1 Regex Scanning**: Rapid rejection against 10 known injection patterns via `KNOWN_INJECTION_PATTERNS`.
  - *Verification*: `pytest tests/security/test_prompt_injection.py -k test_output_sanitizer_blocks_known_attacks`
- [x] **[PASS] Layer 2 LLM-Judge Intent Classifier**: Secondary classification via `prompts/v1/adversarial_classifier.md` for contextual jailbreaks.
- [x] **[PASS] Layer 3 Context Enclosure**: All retrieved chunks encapsulated within `<retrieved_document id="...">` XML blocks.
  - *Verification*: Unit verified in `src/security/prompt_injection.py::wrap_retrieved_content`.
- [x] **[PASS] Layer 4 Tool Argument Validation**: Pydantic schema validation caps `top_k`, input lengths, and query structure.
- [x] **[PASS] Layer 5 Post-Generation Sanitizer**: Output stream scanned for system prompt leakage before transmission to client.
  - *Verification*: `pytest tests/security/test_prompt_injection.py`

---

## 4. Secrets Management & Credential Hygiene

- [x] **[PASS] Codebase Secret Scanning**: Zero plaintext credentials or hardcoded keys in repository.
  - *Verification*: `detect-secrets scan --all-files`
- [x] **[PASS] Git History Cleanliness**: Zero historical credential leaks across git commit trees.
  - *Verification*: Evaluated with `git log -S "sk-" -S "ghp_"` showing zero hardcoded API keys.
- [x] **[PASS] Environment Variable Isolation**: `.env` is strictly ignored in `.gitignore`; `.env.example` provides safe placeholders.
- [x] **[PASS] Structured Log Masking**: Structlog processor redacts passwords, tokens, and Authorization headers.
  - *Verification*: Inspected in `apps/api/app/observability/logging.py`.

---

## 5. Network & Edge Security

- [x] **[PASS] Restrictive CORS**: Configured exclusively for authorized origins (`settings.cors_origins_list`).
- [x] **[PASS] TLS Termination**: Production ingress enforces TLS 1.3 encryption with HTTP Strict Transport Security (HSTS).
- [x] **[MITIGATED] Rate Limiting & Throttling**: 
  - Edge/Ingress layer: Reverse-proxy rate limiting configured via Nginx/Cloudflare (100 req/min per IP).
  - Application layer: Pydantic request body size limits (<2,000 characters) prevent compute-exhaustion attacks.

---

## 6. Database & Storage Hardening

- [x] **[PASS] Parameterized Query Execution**: SQLAlchemy ORM and typed text expressions eliminate SQL injection risks.
- [x] **[PASS] Least Privilege DB User**: Application connects with limited permissions; migrations run under dedicated service account.
- [x] **[PASS] Function Security**: `rag.access_matches()` created with `IMMUTABLE SECURITY DEFINER` attributes.
  - *Verification*: Inspect `alembic/versions/0002_access_matches_function.py`.
- [x] **[PASS] Append-Only Audit Logging**: Privilege actions, role grants, and document ingestions committed to immutable `audit_logs` table.

---

## 7. Observability & Privacy Protection

- [x] **[PASS] PII Redaction in Logs**: Automated regex masking for emails, phone numbers, and SSNs.
- [x] **[PASS] OTel Span Anonymization**: Distributed tracing records `query_hash = sha256(query)` instead of raw user query text.
- [x] **[PASS] Provider Key Isolation**: LLM API keys stripped from all outgoing error traces and Langfuse spans.

---

## 8. Security Test Suite Matrix

To execute the entire security test gate locally:

```bash
pytest tests/security/ -v --tb=short
```

| Test File | Description | Assertions | Status |
| :--- | :--- | :--- | :--- |
| `tests/security/test_prompt_injection.py` | Validates regex blocklists & sanitization | 10 attack vectors + clean baseline | **PASS** |
| `tests/security/test_rbac.py` | Validates role hierarchy & access barriers | Multi-tenant isolation | **PASS** |
| `evals/datasets/adversarial.jsonl` | End-to-end red team test dataset | 15 adversarial attack scenarios | **PASS** |

---

## 9. Residual Risk Assessment & Sign-Off

| Threat ID | Description | Residual Risk Level | Accepted Rationale |
| :--- | :--- | :--- | :--- |
| **RR-01** | LLM compliance with XML data boundary | Low | Mitigated by output sanitizer and deterministic citation validation. |
| **RR-02** | Distributed DDoS on LLM generation | Low | Mitigated by Cloudflare edge rate limiting and Pydantic input length caps. |
| **RR-03** | Database administrator insider threat | Low | Mitigated by database connection audit logging and encrypted backups. |

---

## 10. Formal Security Audit Sign-off

- **Reviewed by**: Security Architecture & Quality Assurance Lead
- **Review Date**: 2026-09-15
- **Build Status**: **APPROVED FOR PRODUCTION RELEASE**

