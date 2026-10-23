"""Job-queue primitive tests (core/jobs.py) against the shared FakeRedis.

Pins the reliable-queue mechanics: enqueue creates the job record and the
queue entry; fetch moves the id to :processing and flips status; complete/
fail clear :processing and record the outcome; expired queued jobs are
dropped by fetch; the startup orphan sweep re-queues stranded jobs.
"""

from __future__ import annotations

import json

import pytest

from apps.api.app.core import jobs
from tests.fakes import FakeRedis


@pytest.fixture
def store() -> FakeRedis:
    return FakeRedis()


@pytest.mark.asyncio
async def test_enqueue_creates_job_and_queue_entry(store: FakeRedis) -> None:
    job_id = await jobs.enqueue(store, kind="ingest", payload={"filename": "a.md"})
    raw = await store.get(f"job:{job_id}")
    assert raw is not None
    job = json.loads(raw)
    assert job["kind"] == "ingest"
    assert job["status"] == "queued"
    assert job["payload"] == {"filename": "a.md"}
    assert await store.lrange("queue:ingest", 0, -1) == [job_id]


@pytest.mark.asyncio
async def test_fetch_moves_to_processing_and_marks_started(store: FakeRedis) -> None:
    job_id = await jobs.enqueue(store, kind="ingest", payload={})
    job = await jobs.fetch_next(store, kind="ingest", timeout=1)
    assert job is not None and job["id"] == job_id
    assert job["status"] == "processing"
    assert job["started_at"] is not None
    # The id moved from the queue to the processing list.
    assert await store.lrange("queue:ingest", 0, -1) == []
    assert await store.lrange("queue:ingest:processing", 0, -1) == [job_id]


@pytest.mark.asyncio
async def test_fetch_returns_none_when_idle(store: FakeRedis) -> None:
    assert await jobs.fetch_next(store, kind="ingest", timeout=0) is None


@pytest.mark.asyncio
async def test_fetch_drops_expired_job_record(store: FakeRedis) -> None:
    """A queued id whose job record TTL'd out is dropped, not crashed on."""
    await store.lpush("queue:ingest", "ghost-job")
    assert await jobs.fetch_next(store, kind="ingest", timeout=1) is None
    assert await store.lrange("queue:ingest:processing", 0, -1) == []


@pytest.mark.asyncio
async def test_complete_records_result_and_clears_processing(store: FakeRedis) -> None:
    job_id = await jobs.enqueue(store, kind="ingest", payload={})
    job = await jobs.fetch_next(store, kind="ingest", timeout=1)
    await jobs.complete(store, job, result={"document_id": "doc-1"})
    done = await jobs.get_job(store, job_id)
    assert done["status"] == "done"
    assert done["result"] == {"document_id": "doc-1"}
    assert done["finished_at"] is not None
    assert await store.lrange("queue:ingest:processing", 0, -1) == []


@pytest.mark.asyncio
async def test_fail_records_error_and_clears_processing(store: FakeRedis) -> None:
    job_id = await jobs.enqueue(store, kind="ingest", payload={})
    job = await jobs.fetch_next(store, kind="ingest", timeout=1)
    await jobs.fail(store, job, error="boom")
    failed = await jobs.get_job(store, job_id)
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"
    assert await store.lrange("queue:ingest:processing", 0, -1) == []


@pytest.mark.asyncio
async def test_requeue_orphans_requeues_processing_jobs(store: FakeRedis) -> None:
    # Simulate a crashed worker: job in :processing with status processing.
    job_id = await jobs.enqueue(store, kind="ingest", payload={})
    await jobs.fetch_next(store, kind="ingest", timeout=1)
    # Done/failed jobs must NOT be re-queued.
    done_id = await jobs.enqueue(store, kind="ingest", payload={})
    done_job = await jobs.fetch_next(store, kind="ingest", timeout=1)
    await jobs.complete(store, done_job, result={})

    requeued = await jobs.requeue_orphans(store, kind="ingest")
    assert requeued == 1
    assert await store.lrange("queue:ingest", 0, -1) == [job_id]
    # The completed job stays done (not re-queued) and its id was already
    # cleared from :processing by complete().
    assert await store.lrange("queue:ingest:processing", 0, -1) == []
    job = await jobs.get_job(store, job_id)
    assert job["status"] == "queued"
    assert job["started_at"] is None
    assert (await jobs.get_job(store, done_id))["status"] == "done"


@pytest.mark.asyncio
async def test_get_job_missing_returns_none(store: FakeRedis) -> None:
    assert await jobs.get_job(store, "nope") is None
