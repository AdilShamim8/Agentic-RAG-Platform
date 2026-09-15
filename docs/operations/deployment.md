# Production Deployment & Infrastructure Guide

> Step-by-step production operations, container orchestration, zero-downtime deployment pipelines, and post-deployment validation for local development, staging environments, and high-availability Kubernetes clusters.

---

## 1. Environment Architecture & Port Topology

| Service | Container Name | Internal Port | Host Port | Technology | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **API Gateway** | `rag-api` | 8000 | `8000` | FastAPI / Uvicorn | REST endpoints, Orchestrator, Auth |
| **Web Interface** | `rag-web` | 3000 | `3000` | React / Next.js | Conversational UI, Admin Console |
| **PostgreSQL + pgvector** | `rag-postgres` | 5432 | `5432` | PostgreSQL 16 + pgvector | Document chunks, embeddings, RBAC, audit |
| **Cache Store** | `rag-redis` | 6379 | `6379` | Redis 7 Alpine | Embedding cache, query cache, rate limits |
| **Observability Server** | `rag-langfuse` | 3000 | `3001` | Langfuse v2 | LLM tracing, evaluation traces, latency |

---

## 2. Local Development Deployment

```bash
# 1. Clone repository
git clone https://github.com/AdilShamim8/Agentic-RAG-Platform.git agentic-rag-platform
cd agentic-rag-platform

# 2. Configure environment credentials
cp .env.example .env
# Edit .env and supply your OPENAI_API_KEY, JWT_SECRET, and LANGFUSE credentials

# 3. Spin up complete infrastructure stack
make up

# 4. Apply database migrations & seed reference accounts
make migrate
make seed

# 5. Ingest local reference documentation
make ingest-local
```

### Verification Endpoints
- **API Health**: `http://localhost:8000/health/ready` (expect HTTP 200 with subsystem statuses `ok`)
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **Web UI Client**: `http://localhost:3000`
- **Langfuse Tracing Dashboard**: `http://localhost:3001`

---

## 3. Staging Deployment (Single VM)

### Recommended Hardware Spec
- **Compute**: 4 vCPUs (x86_64, AVX2 enabled for optimal PyTorch cross-encoder inference)
- **Memory**: 16 GB RAM (allocates 4GB shared buffers for pgvector, 4GB for model weights)
- **Disk**: 100 GB NVMe SSD (minimum 3000 IOPS)
- **OS**: Ubuntu 22.04 LTS with Docker 24+ & Docker Compose v2

### Deployment Steps

```bash
# Clone to deployment directory
git clone https://github.com/AdilShamim8/Agentic-RAG-Platform.git /opt/agentic-rag
cd /opt/agentic-rag

# Configure staging secrets
cp .env.example .env
# Inject high-entropy JWT secrets
export JWT_SECRET=$(openssl rand -hex 32)
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${JWT_SECRET}|" .env

# Switch configuration to staging profile
cp configs/staging/config.yaml configs/base/config.yaml

# Pull and start services in background
docker compose -f docker-compose.yml up -d --build

# Run database schema migrations
docker compose exec api python -m alembic upgrade head

# Seed testing users and reference documents
docker compose exec api python -m scripts.seed
```

### Automated Nightly Backup Cron
Add the following entry to `/etc/cron.d/rag_backup`:

```cron
0 2 * * * root cd /opt/agentic-rag && docker compose exec -T postgres pg_dump -U rag -Fc rag > /opt/backups/rag-$(date +\%Y\%m\%d).dump && aws s3 cp /opt/backups/rag-$(date +\%Y\%m\%d).dump s3://enterprise-rag-backups/staging/ --storage-class STANDARD_IA
```

---

## 4. Production High-Availability Deployment

### Kubernetes Architecture (EKS / GKE)

Kubernetes manifests are maintained in `infra/k8s/`:

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -k infra/k8s/overlays/production/
```

### Key Workload Specifications
- **API Deployment**: 3+ replicas with `HorizontalPodAutoscaler` scaling on CPU utilization (>70%) and custom Prometheus metric `rag_query_latency_seconds_p95`.
- **Pod Disruption Budget (PDB)**: Enforces `minAvailable: 2` to prevent downtime during cluster upgrades.
- **Managed Database Layer**: Dedicated RDS PostgreSQL 16 instance with Multi-AZ replication, `pgvector` extension, and automated WAL archiving.
- **Managed Object Store**: S3 bucket with versioning and object lock for immutable audit logs.

---

## 5. Health Probes & Load Balancer Integration

The API provides two distinct probe endpoints in [`apps/api/app/routers/health.py`](../../apps/api/app/routers/health.py):

### 5.1. Liveness Probe (`GET /health`)
- Used by Kubernetes kubelet to detect deadlocked worker processes.
- Returns HTTP 200 immediately if process event loop is responsive.

### 5.2. Readiness Probe (`GET /health/ready`)
- Used by load balancers and ingress controllers to route live traffic.
- Validates that all downstream dependencies are operating within latency tolerances.

**Sample Response Payload**:
```json
{
  "status": "ready",
  "version": "1.0.0",
  "subsystems": {
    "database": "ok",
    "redis": "ok",
    "embedding_model": "ok",
    "reranker_model": "ok",
    "llm_provider": "ok"
  }
}
```

---

## 6. Zero-Downtime Rollback Protocols

1. **Application Code Rollback**:
   Re-tag and deploy the previous immutable Docker image tag:
   ```bash
   kubectl set image deployment/rag-api rag-api=ghcr.io/adilshamim8/agentic-rag-api:v1.2.3
   ```
2. **Database Schema Rollback**:
   Every Alembic migration script includes an audited, verified `downgrade()` implementation:
   ```bash
   docker compose exec api alembic downgrade -1
   ```
3. **Prompt & Configuration Rollback**:
   Prompts are versioned in `prompts/v1/` and `prompts/v2/`. Roll back instantly without container rebuilds by updating `configs/prod/config.yaml`:
   ```yaml
   prompts:
     version: "v1"
   ```
   Execute hot-reload without downtime.

---

## 7. Post-Deployment Smoke Verification

Execute following every release:

```bash
# 1. Verify all subsystem readiness
curl -f -s http://localhost:8000/health/ready | jq .

# 2. Execute 10-item CI smoke evaluation suite
make eval-smoke

# 3. Validate live query with verified citation attribution
curl -s -X POST http://localhost:8000/query \
  -H "Authorization: Bearer $TEST_USER_JWT" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the policy for remote work?"}' | jq .
```

