# Database Backup, Disaster Recovery & PITR Guide

> Comprehensive backup protocols, WAL archiving, Point-In-Time-Recovery (PITR), and disaster recovery validation for PostgreSQL with `pgvector`, Redis caches, and S3 object storage.

---

## 1. Backup Scope & SLA Metrics

| Asset Tier | Data Stored | Frequency | Target Storage | Retention | RPO Target | RTO Target |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL Primary** | Chunks, HNSW vectors, users, RBAC policies, audit log | Continuous WAL + Daily Dump | Encrypted S3 Bucket | 30 Days (Glacier 1 yr) | < 5 mins | < 15 mins |
| **Document Storage** | Raw PDFs, source Markdown, metadata | Continuous (S3 Versioning) | S3 Standard | Indefinite | 0 mins | < 5 mins |
| **Langfuse Observability** | Traces, LLM execution spans, evaluations | Daily snapshot | S3 Bucket | 90 Days | 24 hours | < 1 hour |
| **Configuration State** | `.env`, versioned prompts, YAML profiles | Git repo + Secrets Manager | Git / Vault | Git history | 0 mins | < 5 mins |

---

## 2. Automated Backup Execution

We use PostgreSQL custom binary archive format (`pg_dump -Fc`). The custom format compresses natively, enables parallel multi-core restoration (`pg_restore -j`), and allows selective table extraction without parsing raw SQL text files.

### 2.1. Daily Automated Snapshot Cron

Add to `/etc/cron.d/rag_database_backup`:

```cron
# Execute daily at 02:00 UTC with SHA-256 verification
0 2 * * * root /usr/local/bin/backup_rag_postgres.sh >> /var/log/rag_backup.log 2>&1
```

### 2.2. Production Backup Script (`/usr/local/bin/backup_rag_postgres.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DATE=$(date -u +%Y%m%d_%H%M%SZ)
BACKUP_DIR="/opt/backups/daily"
BACKUP_FILE="${BACKUP_DIR}/rag_${BACKUP_DATE}.dump"
S3_BUCKET="s3://enterprise-rag-backups/production/database"

mkdir -p "${BACKUP_DIR}"

echo "[${BACKUP_DATE}] Initiating pg_dump..."
docker compose exec -T postgres pg_dump \
  -U rag \
  -d rag \
  -Fc \
  -b \
  -v \
  -f "/tmp/backup.dump"

docker cp "rag-postgres:/tmp/backup.dump" "${BACKUP_FILE}"
docker compose exec -T postgres rm -f "/tmp/backup.dump"

# Generate checksum
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"

echo "[${BACKUP_DATE}] Uploading to S3..."
aws s3 cp "${BACKUP_FILE}" "${S3_BUCKET}/" --storage-class STANDARD_IA
aws s3 cp "${BACKUP_FILE}.sha256" "${S3_BUCKET}/"

# Prune local files older than 7 days
find "${BACKUP_DIR}" -type f -name "rag_*.dump*" -mtime +7 -delete
echo "[${BACKUP_DATE}] Backup successfully completed."
```

---

## 3. Disaster Recovery & Restoration Procedure

> [!IMPORTANT]
> **Vector Extension Ordering**: When restoring into a newly initialized database, the `vector` extension MUST be created **before** importing data. If omitted, `pg_restore` will abort with `ERROR: type "vector" does not exist` when attempting to restore the `document_chunks` table.

### Step-by-Step Restoration Protocol

```bash
# Step 1: Download backup archive and verify checksum
aws s3 cp s3://enterprise-rag-backups/production/database/rag_20260915_020000Z.dump .
aws s3 cp s3://enterprise-rag-backups/production/database/rag_20260915_020000Z.dump.sha256 .
sha256sum -c rag_20260915_020000Z.dump.sha256

# Step 2: Quiesce write operations by halting API and Worker containers
docker compose stop api worker

# Step 3: Recreate empty database
docker compose exec postgres psql -U rag -c "DROP DATABASE IF EXISTS rag_restore_staging;"
docker compose exec postgres psql -U rag -c "CREATE DATABASE rag_restore_staging OWNER rag;"

# Step 4: CRITICAL - Pre-initialize extensions in target database
docker compose exec postgres psql -U rag -d rag_restore_staging -c "
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";
  CREATE SCHEMA IF NOT EXISTS rag;
"

# Step 5: Execute multi-threaded restore with optimized memory allocation
docker compose exec -T postgres psql -U rag -d rag_restore_staging -c "SET maintenance_work_mem = '2GB';"
docker cp rag_20260915_020000Z.dump rag-postgres:/tmp/restore.dump
docker compose exec -T postgres pg_restore \
  -U rag \
  -d rag_restore_staging \
  -j 4 \
  --no-owner \
  --no-privileges \
  /tmp/restore.dump

docker compose exec -T postgres rm -f /tmp/restore.dump

# Step 6: Atomic switch from staging to live database
docker compose exec postgres psql -U rag -c "
  DROP DATABASE IF EXISTS rag_backup_old;
  ALTER DATABASE rag RENAME TO rag_backup_old;
  ALTER DATABASE rag_restore_staging RENAME TO rag;
"

# Step 7: Restart application and verify health
docker compose start api worker
curl -f http://localhost:8000/health/ready
```

---

## 4. Continuous Point-In-Time-Recovery (PITR)

For zero-data-loss compliance on managed platforms (AWS RDS / GCP Cloud SQL):
1. Enable continuous Write-Ahead Log (WAL) archiving with a 5-minute archival period.
2. In the cloud console, select **Restore to Point-in-Time**.
3. Specify the target recovery epoch down to the exact second prior to the incident (e.g., prior to an errant table drop).
4. Point DNS or connection strings to the new replica once synchronized.

---

## 5. Monthly Recovery Validation Drill

Once every 30 days, operations executes a live recovery drill in staging:
1. Select an arbitrary backup archive from the previous 7 days.
2. Spin up an isolated PostgreSQL container.
3. Perform the complete Step 1–Step 7 restore pipeline.
4. Execute `pytest tests/integration/` against the restored database instance.
5. Record recovery duration, RTO achieved, and sign off in `docs/operations/dr-logs/`.

