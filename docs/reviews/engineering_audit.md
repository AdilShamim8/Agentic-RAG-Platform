# Engineering Audit — Agentic RAG Platform

Audit baseline: commit `628df28` (clone state). All fixes in this review are
on `main`, one commit per issue cluster (see `issue_register.json` for the
commit map). Validation environment: userspace PostgreSQL 17.11 + pgvector
0.8.0, Python 3.12, Node 24; Docker unavailable (documented as BLOCKED where
relevant). No real LLM API key (mock provider used; labeled everywhere).

## 1. Scope and method

Investigated, reproduced, fixed, and re-tested: startup/config, auth and
authorization, document lifecycle, agent orchestration, citation validity,
retrieval freshness, prompt injection, memory, conversations/persistence,
health/admin truthfulness, evaluation validity, CI, frontend, dependency
posture. Nothing was accepted from README claims; every finding below was
reproduced against the running stack before fixing, and every fix carries a
regression test listed in `test_matrix.md`.

## 2. Architecture / data-flow map (as found -> as fixed)

**Query path (fixed):**
Browser (login page, bearer token; was: no auth header at all) -> Next.js
rewrite `/api/:path*` -> `POST /query` (`routers/query.py`; request validated,
`get_auth_user` -> AuthUser; was: ORM User leaked into services) ->
`query_service.run_agentic_query` (resolves/creates the caller's conversation;
persists user+assistant messages with citations JSONB + trace_id; was:
"TODO: persist") -> `orchestrator.run_agent`:
classification -> **query-level injection screen (was: never called)** ->
bounded plan/execute loop (per-step failures tolerated; replan with feedback
while budget remains; was: terminal on first insufficient evidence and on any
tool exception) -> `retrieve` (dense + lexical, both with
`rag.access_matches` RBAC **and** effective-date windows in the SQL WHERE;
was: RBAC params crashed asyncpg with AmbiguousParameterError on every
no-filter query, freshness unenforced) -> RRF fusion (1-based ranks,
non-mutating) -> reranker (`FlagReranker`, the real API; was: import of a
nonexistent class) -> evidence sufficiency -> generation (evidence wrapped as
data with a treat-as-data rule) -> output sanitizer (was: never wired) ->
citation validation (claims from the answer's own sentences; bounds-checked
markers; fail-closed judge; was: evidence validated against itself) ->
response with citations + trace_id.

**Ingestion path (fixed):** upload validation (extension whitelist, magic
bytes, 20MB cap) -> parser (pypdf/docx/trafilatura/markdown) -> cleaner ->
configured chunker -> embedder + FTS indexing -> version record + audit log
(was: `NotImplementedError`). Duplicate content is idempotent.

**Evaluation path (fixed):** fixture corpus with stable UUIDs -> seeded
idempotently -> runner executes every baseline for real (was:
`"[not implemented]"` placeholders) -> deterministic metrics + honest
unscored reasons -> CI gates that fail on missing data (was: a gate reading a
never-existing field, unable to fail).

## 3. Findings (risk-ranked; full detail in issue_register.json)

### P0 (system cannot operate / core security)
1. **Compose omitted required secrets** - API and worker crashed at import
   (APP_SECRET_KEY/JWT_SECRET). Fixed in `docker-compose.yml` + contract tests.
2. **Type-confused auth dependency** - ORM `User` flowed into services/agents;
   `user.permissions` became unawaited coroutines; tool permission checks
   compared against a coroutine. Fixed via a single `get_auth_user` dependency.
3. **Retrieval SQL had never executed end-to-end** - NULL-bound optional
   filters made asyncpg raise `AmbiguousParameterError`; masked upstream by
   the tool-registry and reranker failures. Fixed with dynamic filter
   assembly; the entire stack now runs for real.
4. **Tool registry was empty in the app path** - nothing imported the tool
   modules, so `execute_tool("search_documents")` raised `Unknown tool`.
5. **Frontend had no auth** - no login UI, no bearer header (guaranteed 401),
   and network errors rendered as assistant answers. Fixed with a login page,
   an auth lib, error states, and conversation chaining.

### P1 (core journey / contracts / evaluation validity)
6. Documented JSON login returned 422 (OAuth2-form-only endpoint).
7. Reranker imported a nonexistent FlagEmbedding class; default strategy broken.
8. Freshness was decorative: effective dates selected but never filtered;
   expired/future documents fully retrievable. Now SQL-enforced with range
   intersection for historical queries.
9. Citation validation validated evidence against itself; fabricated markers
   silently dropped; no abstention path. Rewritten around answer claims with
   a fail-closed judge.
10. Agent had no re-plan loop (contradicting its own state-machine doc) and
    died on any tool exception; the planner prompt never documented tool
    schemas so planners hallucinated args the registry rejected.
11. Document/conversation/memory services were TODO stubs; messages were
    never persisted; conversation ids were invented per response.
12. Injection defenses were dead code: `classify_input` and `sanitize_output`
    were never called. Both wired into the query path.
13. Evaluation was decorative: placeholder ground truth, stub runner, a CI
    gate that could never fail, corrupted CI branch triggers (`ain]`).
14. RBAC security tests were empty `pass` stubs; replaced with real seeded
    retrieval tests.

### P2 (quality/honesty)
15. RRF 0-based ranks + in-place mutation of shared chunks.
16. Registry schema validation covered 3 types only; full subset validator
    added. `get_document_versions` tool returned a stub; real implementation.
17. Health/admin endpoints fabricated states ("redis connected: true" with no
    Redis client in the codebase); now honest, real aggregates.
18. Memory service stubs; memory_search tool scoping verified.
19. pyproject: broken `rag` console script, undeclared `pypdf`, unused
    `sentence-transformers` (pulled torch) and `python-jwt` removed.
20. Makefile eval targets called CLI flags that do not exist.

## 4. What works now (with evidence)

- 207 backend tests + frontend lint/tsc/build, all green; matrix in
  `test_matrix.md` with per-scenario evidence codes.
- End-to-end agent journey over real PostgreSQL: login (JSON, per docs) ->
  authorized retrieval (RBAC + freshness in SQL) -> grounded answer with
  verified, claim-mapped citations -> persisted multi-turn conversation.
- Full-golden evaluation across six baselines with real, differentiated
  numbers (mock provider, labeled): agentic behavior compliance 0.960 /
  unexpected-failure 0.040 (best) with all 50/50 rows scored (clarify and
  conflict-report rows included since the follow-up series), hybrid
  0.880/0.100, lexical 0.580/0.420. Reports: `evals/reports/` incl.
  `comparison.md`.
- Follow-up hardening series (this session, commits c1ba4dc..aaebb78):
  - Web app fresh-clone integrity repaired (gitignore `lib/` collision
    had silently dropped `src/lib/auth.ts` from the repo).
  - Refresh tokens live in HttpOnly cookies with per-use rotation, a
    revocation deny list, replay detection with audit trail, and a real
    `/auth/logout`; the browser no longer stores any refresh token.
  - Login rate limiting is Redis-backed (sorted-set sliding window) with
    a per-process in-memory fallback; identical semantics in both.
  - The worker is real: reliable-queue Redis consumer with orphan
    recovery, SIGTERM-safe shutdown, heartbeat healthcheck; async ingest
    via `POST /documents/ingest-async` + job-status polling (owner/admin
    ACL), 503 (never silent) when Redis is down.
  - Clarify and conflict-report agent behaviors implemented and scored
    in the eval harness (was: permanently unscored rows).
  - Per-event retrieval cost persisted (`retrieval_events.cost_usd`);
    `/admin/stats` reports the real 24h sum instead of a hardcoded 0.0.

## 5. Readiness assessment

- **Local development: READY.** `make up` + migrate + seed + seed-fixtures +
  ingest (sync or queued through the worker) + query all verified (directly
  against PostgreSQL 17+pgvector where Docker was unavailable; CI covers the
  compose path).
- **Staging: READY with caveats.** Deterministic offline providers are the
  default test path; real providers need a key and a first-run smoke.
  Enable REFRESH_COOKIE_SECURE (TLS) and keep one worker replica until
  multi-worker orphan recovery is designed.
- **Production: NOT READY.** Remaining risks below must be addressed first.

## 6. Remaining risks (prioritized)

1. **No real-provider runtime validation of LLM judging / bge-m3 / bge
   reranker in this environment** - contract-tested only; nightly CI
   exercises real providers when secrets exist. (P1, environment-blocked)
2. **Async-ingest job payloads carry file content (base64) through
   Redis.** Bounded by the 20 MB upload cap and job TTL; large-scale
   production should pass object-store pointers instead. (P3)
3. **Worker orphan recovery assumes a single worker replica** (no
   heartbeat protocol); with multiple replicas a crashed worker's job
   waits for manual re-drive. Eval jobs are still CLI-only. (P2, follow-up)
4. **Offline conflict detection is a number+unit heuristic** (days/week,
   $/period, weeks of leave, %). Non-numeric conflicts (yes/no decisions,
   dates, procedures) need the real LLM judge. (P3)
5. **REFRESH_COOKIE_SECURE defaults to false** for plain-http local dev;
   MUST be enabled behind TLS. The web access token still lives in
   sessionStorage for the demo (short-lived; the long-lived credential is
   the HttpOnly cookie). (P2, deployment checklist)
6. **Rate-limiter backend is resolved once per process** - if Redis dies
   mid-flight, limiting stays in per-process memory until restart.
   X-Forwarded-For still requires a trusted proxy. (P3)
7. **Content sniffing is best-effort**; deep parser fuzzing not performed.
   (P3)
8. Demo credentials (`alice@demo.dev`/`password123`, `rag:rag` DB) are
   development-only; production must not reuse them (documented in
   QUICKSTART and SECURITY.md).

## 7. How to run and verify

```bash
# Safe (non-destructive)
cp .env.example .env            # fill APP_SECRET_KEY + JWT_SECRET (>=32 chars each) + keys
make up                         # postgres, redis, api, web, worker, langfuse
make migrate && make seed && make seed-fixtures
curl -s http://localhost:8000/health/ready
curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"alice@demo.dev","password":"password123"}' | jq -r .access_token
# then POST /query with Authorization: Bearer <token>
make test                       # unit + integration
make test-security              # RBAC + injection (real retrieval tests)
make eval-smoke                 # gated, fails on missing metrics
make eval && make eval-compare  # full golden + comparison.md

# Destructive (dev data only - never run against production)
make db-reset
```

Verification of this audit: `pytest tests/unit tests/security tests/integration
tests/regression` with the environment from `tests/conftest.py` (deterministic
offline models) against a migrated + seeded database.
