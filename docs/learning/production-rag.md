# Production RAG

> What changes when you move an Agentic RAG system from a notebook demo to a deployed, monitored, production service.

## Concept

A RAG prototype is a Jupyter notebook: one model, one retrieval call, no error handling, no auth, no monitoring. A production RAG system is a service with SLAs, multiple failure modes, quality gates, rollback procedures, and live traffic.

The gap between "it works on my laptop" and "it handles 1000 queries/day reliably" is significant. This document describes the engineering decisions required to cross that gap.

## Why it matters

Production RAG failures have real consequences:

- A hallucinated answer to a legal or medical question causes harm.
- A data leak from a broken access control exposes confidential documents.
- A 10-second latency spike causes users to abandon the system.
- A prompt regression degrades quality silently for days before anyone notices.

Production readiness means building for failure, not just for the happy path.

## What changes in production

### 1. Auth and RBAC

In a demo, there is one user with access to everything. In production:

- Every request carries a JWT (validated on every `/query` call).
- The user's role and project memberships are loaded from the database.
- The RBAC `access_matches()` function filters chunks **before** retrieval — never after.
- Unauthorized access attempts are logged to `audit_logs`.

### 2. Quality gates in CI

Every pull request triggers a smoke evaluation (10-item golden dataset). If faithfulness drops below `0.85`, the build fails. No bad prompt or retrieval change reaches production without being caught first.

```yaml
# .github/workflows/ci.yml
- name: eval-smoke
  run: make eval-smoke
  env:
    EVAL_FAITHFULNESS_THRESHOLD: "0.85"
```

### 3. Prompt versioning and rollback

Prompts are stored in `prompts/v1/`, `prompts/v2/`, etc. The active version is a config value:

```yaml
# configs/prod/config.yaml
prompt_version: v2
```

Rolling back a bad prompt is a config change + restart — no code deploy, no DB migration. This is the fastest possible rollback path for the most common type of quality regression.

### 4. Retry and fallback

LLM calls are wrapped in retry logic (`src/core/retries.py`):

- 3 attempts with exponential backoff: 1s → 2s → 4s.
- On total failure: return `LLM_TIMEOUT` with a user-friendly message.
- The `LLMProvider` abstraction (`src/llm/provider.py`) allows switching from OpenAI to Anthropic by changing one config value — no code changes.

### 5. Structured error responses

Every failure type has a distinct error code, a user-friendly message, and an internal trace for debugging:

| Failure type | User message | Internal action |
| ------------ | ------------ | --------------- |
| `NO_DOCUMENTS` | "I couldn't find any documents matching your question." | Log retrieval query; alert if spike |
| `INSUFFICIENT_EVIDENCE` | "I don't have enough evidence to answer this confidently." | Log retrieved chunks; check corpus coverage |
| `LLM_TIMEOUT` | "The model is taking too long. Please try again." | Alert if > 5% of requests in 5 min |
| `HALLUCINATION_DETECTED` | "I generated an answer I cannot verify." | Save answer to forensics log |
| `AGENT_LOOP` | "I'm having trouble reasoning through this." | Save trace; inspect planner prompt |
| `PROMPT_INJECTION` | "I detected an attempt to manipulate my instructions." | Log input; do not process |

### 6. Observability

See `docs/learning/observability.md` for the full picture. The short version:

- Every request produces a **trace** in Langfuse (OpenTelemetry).
- **Prometheus metrics** expose latency, failure rate, token cost.
- **structlog** JSON logs are shipped to a log aggregator.
- **Audit logs** record every privileged action in the database.

Without observability, production debugging is archaeology. With it, you can answer "why did this query fail?" in under 2 minutes.

### 7. Data backups

```
Every night at 02:00 UTC:
  pg_dump rag | gzip | s3 cp → s3://backups/agentic-rag/YYYYMMDD.sql.gz
Retention: 30 days
Monthly drill: restore from backup in staging, verify query works end-to-end
```

A backup you've never restored is not a backup.

### 8. Blue/green deployment

Every production deployment uses blue/green:

1. Deploy new version to "green" (idle) environment.
2. Run smoke eval against green.
3. Switch traffic from blue → green (via load balancer rule).
4. Keep blue warm for 30 minutes.
5. If green alerts fire, switch back to blue in < 60 seconds.

### 9. Database migrations

Every Alembic migration must have a tested `downgrade()` function. Before merging:

```bash
# Verify the migration round-trips
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

A migration without a downgrade is a one-way door.

### 10. Secrets management

- Secrets live in env vars only — never in config files, never in code.
- Pre-commit `detect-secrets` hook scans every commit for accidental secret inclusion.
- In production, secrets are injected from AWS Secrets Manager / GCP Secret Manager / HashiCorp Vault.
- structlog redaction filter strips known secret patterns from log output.

## Production checklist

Before going live, verify:

- [ ] `/health/ready` returns 200 with all subsystems `ok`.
- [ ] Smoke eval passes (faithfulness ≥ 0.85).
- [ ] All env vars are set (no `.env.example` values in production).
- [ ] Nightly backup cron is running.
- [ ] Prometheus alerting rules are active.
- [ ] Langfuse is receiving traces.
- [ ] A rollback drill was performed in staging.
- [ ] The runbook (`docs/operations/runbook.md`) is up to date.

## Where it appears in the code

| File | Purpose |
| ---- | ------- |
| `apps/api/app/main.py` | Health endpoints, Prometheus middleware, startup checks |
| `src/core/retries.py` | LLM retry logic with exponential backoff |
| `src/llm/provider.py` | LLM provider abstraction (swap OpenAI → Anthropic via config) |
| `src/security/` | Prompt injection, RBAC enforcement |
| `src/observability/` | Tracing, metrics |
| `alembic/` | Database migrations with `upgrade()` and `downgrade()` |
| `configs/prod/config.yaml` | Production configuration |
| `docs/operations/deployment.md` | Step-by-step deployment guide |
| `docs/operations/runbook.md` | On-call runbook |
| `docs/operations/backup-restore.md` | Backup and restore procedures |
| `.github/workflows/ci.yml` | CI pipeline with smoke eval gate |

## Failure modes

See `docs/operations/runbook.md` for the complete incident playbook. High-level categories:

- **Retrieval failures** (NO_DOCUMENTS, INSUFFICIENT_EVIDENCE): corpus coverage issue.
- **LLM failures** (LLM_TIMEOUT, HALLUCINATION_DETECTED): provider issue or prompt regression.
- **Agent failures** (AGENT_LOOP): planner prompt issue.
- **Infrastructure failures** (Postgres down, Redis down): see runbook.

## Further reading

- Eugene Yan, "Patterns for Building LLM-based Systems and Products" (2023) — practical production patterns.
- Chip Huyen, "Building LLM Applications for Production" (2023) — comprehensive production guide.
- Google SRE Book — foundational operational practices applicable to any production service.
- Langfuse documentation — https://langfuse.com/docs — for trace-based debugging.
