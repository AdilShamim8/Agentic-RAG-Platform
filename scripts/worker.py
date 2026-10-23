"""Background worker — consumes ingest (and future) jobs from Redis.

Lifecycle:
- connect to Redis (from REDIS_URL) with retry/backoff until it is up
  (compose starts the worker after Redis' healthcheck, but Redis can
  still restart later)
- on start, re-queue jobs stranded in the :processing list by a previous
  crashed worker (single-worker orphan recovery; see core/jobs.py)
- loop: fetch a job (blocking pop with a short timeout so shutdown is
  responsive), dispatch by kind, mark done/failed
- SIGTERM/SIGINT (docker stop): finish the current job, then exit 0

Dispatch table maps job kinds to async handlers
(apps.api.app.services.jobs_service). Handlers are idempotent - delivery
is at-least-once, not exactly-once.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from apps.api.app.core import jobs
from apps.api.app.core.config import settings
from apps.api.app.services.jobs_service import run_ingest_job

logging.basicConfig(
    level=settings.app_log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

POLL_TIMEOUT_SECONDS = 5
REDIS_RETRY_SECONDS = 2.0
HEARTBEAT_FILE = "/tmp/rag-worker-heartbeat"
HEARTBEAT_MAX_AGE_SECONDS = 30

# job kind -> async handler(payload: dict) -> dict result
HANDLERS = {
    "ingest": run_ingest_job,
}


def _heartbeat() -> None:
    """Touch the liveness file consumed by the compose healthcheck."""
    try:
        with open(HEARTBEAT_FILE, "w") as fh:
            fh.write(str(HEARTBEAT_MAX_AGE_SECONDS))
    except OSError:
        pass  # read-only fs: the healthcheck falls back to process state


class Worker:
    def __init__(self) -> None:
        self._client = None
        self._stop = False

    def request_stop(self) -> None:
        log.info("Shutdown requested; finishing the current job...")
        self._stop = True

    async def connect(self) -> None:
        """Connect to Redis, retrying forever with a short backoff."""
        import redis.asyncio as aioredis

        while not self._stop:
            try:
                client = aioredis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=2.0,
                    socket_timeout=10.0,  # blocking pops need a generous read timeout
                )
                await client.ping()
                self._client = client
                log.info("Connected to Redis at %s", settings.redis_url)
                return
            except Exception as exc:
                log.warning("Redis not reachable (%s); retrying in %.0fs", exc, REDIS_RETRY_SECONDS)
                await asyncio.sleep(REDIS_RETRY_SECONDS)

    async def run(self) -> None:
        await self.connect()
        assert self._client is not None
        requeued = await jobs.requeue_orphans(self._client, kind="ingest")
        if requeued:
            log.info("Re-queued %d orphaned ingest job(s)", requeued)

        while not self._stop:
            _heartbeat()
            try:
                job = await jobs.fetch_next(
                    self._client, kind="ingest", timeout=POLL_TIMEOUT_SECONDS
                )
            except Exception as exc:
                log.error("Queue read failed (%s); reconnecting", exc)
                await asyncio.sleep(REDIS_RETRY_SECONDS)
                await self.connect()
                continue
            if job is None:
                continue  # idle tick - re-check the shutdown flag
            await self._handle(job)

        log.info("Worker stopped cleanly")

    async def _handle(self, job: dict) -> None:
        handler = HANDLERS.get(job.get("kind", ""))
        if handler is None:
            await jobs.fail(self._client, job, error=f"unknown job kind: {job.get('kind')!r}")
            return
        job_id = job["id"]
        log.info("job %s started (kind=%s)", job_id, job["kind"])
        try:
            result = await handler(job.get("payload") or {})
        except Exception as exc:
            log.exception("job %s failed", job_id)
            await jobs.fail(self._client, job, error=str(exc))
        else:
            await jobs.complete(self._client, job, result=result)
            log.info("job %s done: %s", job_id, result)


async def main() -> None:
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
