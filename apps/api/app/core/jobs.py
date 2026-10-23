"""Minimal Redis-backed job queue (reliable-queue pattern).

The worker (scripts/worker.py) consumes background jobs produced by the
API. No RQ/Celery/ARQ dependency - redis-py lists give the same guarantees
we need for this deployment size:

Keys (per job kind, e.g. ``ingest``):
- ``queue:{kind}``            pending job ids (LPUSH by producers)
- ``queue:{kind}:processing`` in-flight job ids (BRPOPLPUSH destination)
- ``job:{id}``                JSON job document, TTL 24h

Semantics: at-least-once. A worker pops a job id with BRPOPLPUSH, which
atomically moves it to the ``:processing`` list BEFORE handling starts -
a worker crash mid-job leaves the id there, and the next worker start's
orphan sweep re-queues anything still marked ``processing``. Idempotent
handlers (ingest dedupes by content hash) make redelivery safe.

The jobs client requires a reachable Redis: unlike the login rate limiter
there is no in-memory fallback, because the producer (API) and consumer
(worker) are different processes - a per-process fallback queue would
silently strand jobs. Endpoints fail with 503 instead.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from apps.api.app.core.config import settings

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 24 * 60 * 60


def _queue_key(kind: str) -> str:
    return f"queue:{kind}"


def _processing_key(kind: str) -> str:
    return f"queue:{kind}:processing"


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


async def enqueue(client, *, kind: str, payload: dict[str, Any]) -> str:
    """Create a job record and push its id onto the kind's queue."""
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "payload": payload,
        "result": None,
        "error": None,
        "enqueued_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    await client.set(_job_key(job_id), json.dumps(job), ex=JOB_TTL_SECONDS)
    await client.lpush(_queue_key(kind), job_id)
    return job_id


async def fetch_next(client, *, kind: str, timeout: int = 5) -> dict | None:
    """Move the next job id to the processing list and return the job.

    Returns None after ``timeout`` seconds with no work (workers use this
    to re-check their shutdown flag).
    """
    job_id = await client.brpoplpush(_queue_key(kind), _processing_key(kind), timeout=timeout)
    if job_id is None:
        return None
    raw = await client.get(_job_key(job_id))
    if raw is None:
        # Job record expired while queued (TTL) - drop the orphan id.
        await client.lrem(_processing_key(kind), 1, job_id)
        return None
    job = json.loads(raw)
    job["status"] = "processing"
    job["started_at"] = time.time()
    await client.set(_job_key(job_id), json.dumps(job), ex=JOB_TTL_SECONDS)
    return job


async def complete(client, job: dict, *, result: dict[str, Any]) -> None:
    job = dict(job)
    job["status"] = "done"
    job["result"] = result
    job["finished_at"] = time.time()
    await client.set(_job_key(job["id"]), json.dumps(job), ex=JOB_TTL_SECONDS)
    await client.lrem(_processing_key(job["kind"]), 1, job["id"])


async def fail(client, job: dict, *, error: str) -> None:
    job = dict(job)
    job["status"] = "failed"
    job["error"] = error[:2000]
    job["finished_at"] = time.time()
    await client.set(_job_key(job["id"]), json.dumps(job), ex=JOB_TTL_SECONDS)
    await client.lrem(_processing_key(job["kind"]), 1, job["id"])


async def get_job(client, job_id: str) -> dict | None:
    raw = await client.get(_job_key(job_id))
    return json.loads(raw) if raw is not None else None


async def requeue_orphans(client, *, kind: str) -> int:
    """Re-queue jobs stranded in :processing (e.g. after a worker crash).

    Called once at worker startup. Single-worker deployments only: with
    several live workers there is no way to tell a crashed worker's job
    from a running one's without heartbeats, so we do not attempt it.
    """
    processing = await client.lrange(_processing_key(kind), 0, -1)
    requeued = 0
    for job_id in processing:
        raw = await client.get(_job_key(job_id))
        if raw is None:
            await client.lrem(_processing_key(kind), 1, job_id)
            continue
        job = json.loads(raw)
        if job.get("status") == "processing":
            job["status"] = "queued"
            job["started_at"] = None
            await client.set(_job_key(job_id), json.dumps(job), ex=JOB_TTL_SECONDS)
            await client.lpush(_queue_key(kind), job_id)
            await client.lrem(_processing_key(kind), 1, job_id)
            requeued += 1
            logger.warning("Re-queued orphaned job %s (%s)", job_id, kind)
    return requeued


_jobs_client = None


async def get_jobs_client():
    """Process-wide Redis client for the job queue. Raises on unreachable Redis.

    Cached after the first successful connection; failures propagate so the
    API can answer 503 (queue unavailable) instead of stranding jobs.
    """
    global _jobs_client
    if _jobs_client is not None:
        return _jobs_client
    import redis.asyncio as aioredis

    client = aioredis.from_url(
        settings.redis_url,
        socket_connect_timeout=1.0,
        socket_timeout=2.0,
    )
    await client.ping()
    _jobs_client = client
    return _jobs_client


def set_jobs_client(client) -> None:
    """Override the process-wide client (tests, embedded deployments)."""
    global _jobs_client
    _jobs_client = client
