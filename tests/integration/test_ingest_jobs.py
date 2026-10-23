"""Async ingest end-to-end tests: API enqueue -> worker handler -> DB.

Covers the full background-ingestion path wired in this fix series:
- POST /documents/ingest-async returns 202 + job id when the queue is up
  and 503 (not a silent fallback) when Redis is unreachable
- the worker's fetch -> handle -> complete cycle really ingests the file
  (document + chunks land in the database) and marks the job done
- GET /documents/jobs/{id} exposes status to the owner only (403 for
  others, admins allowed)
- failing jobs (bad content) are recorded as failed, not retried forever
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.core import jobs
from apps.api.app.core.db import session_scope
from apps.api.app.main import app
from apps.api.app.models.document import Document
from tests.fakes import FakeRedis


@pytest.fixture(autouse=True)
def _fake_queue():
    """Give the app a FakeRedis queue and take it away after the test."""
    store = FakeRedis()
    jobs.set_jobs_client(store)
    yield store
    jobs.set_jobs_client(None)


async def _login(client: AsyncClient, email: str = "alice@demo.dev") -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_ingest_queues_job_and_worker_processes_it(
    _fake_queue: FakeRedis,
) -> None:
    """Full loop: 202 -> worker fetch/handle/complete -> document in DB."""
    from scripts.worker import Worker

    content = (
        "# Async Ingest Test\n\n"
        "The background worker ingests this document outside the request "
        "cycle. It has enough sentences to produce at least one chunk and "
        "pass the empty-text guard. Unique run marker: "
        f"{uuid.uuid4().hex}\n"
    ).encode()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client)
        response = await client.post(
            "/documents/ingest-async",
            files={"file": ("async-test.md", content, "text/markdown")},
            params={"department": "engineering"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert response.json()["status"] == "queued"

    # Run the worker's exact fetch->handle cycle against the fake queue.
    worker = Worker()
    worker._client = _fake_queue
    job = await jobs.fetch_next(_fake_queue, kind="ingest", timeout=1)
    assert job is not None and job["id"] == job_id
    await worker._handle(job)

    done = await jobs.get_job(_fake_queue, job_id)
    assert done["status"] == "done", done
    document_id = done["result"]["document_id"]

    async with session_scope() as session:
        doc = await session.get(Document, uuid.UUID(document_id))
    assert doc is not None
    assert doc.department == "engineering"
    assert doc.deleted_at is None

    # And the status endpoint reports it to the owner.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client)
        status = await client.get(
            f"/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert status.status_code == 200
    assert status.json()["status"] == "done"
    assert status.json()["result"]["document_id"] == document_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_ingest_503_when_queue_unavailable(monkeypatch) -> None:
    """No reachable Redis, no queue: the endpoint must fail loudly (no silent drop).

    CI runs a real Redis service, so clearing the cached client alone is not
    enough - get_jobs_client() would just connect to it successfully. Point
    the queue at a dead port (9/discard: nothing listens there) to force the
    unreachable-queue path end to end.
    """
    monkeypatch.setattr(jobs.settings, "redis_url", "redis://127.0.0.1:9/0")
    jobs.set_jobs_client(None)  # next use builds a client for the dead URL
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client)
        response = await client.post(
            "/documents/ingest-async",
            files={"file": ("x.md", b"# hello world\nsome content\n", "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    jobs.set_jobs_client(None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_ingest_validates_before_queueing(_fake_queue: FakeRedis) -> None:
    """Bad files are rejected at the API, not inside the worker."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client)
        bad_ext = await client.post(
            "/documents/ingest-async",
            files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
        )
        empty = await client.post(
            "/documents/ingest-async",
            files={"file": ("empty.md", b"", "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert bad_ext.status_code == 400
    assert empty.status_code == 400
    assert await _fake_queue.lrange("queue:ingest", 0, -1) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_status_visible_to_owner_and_admin_only(_fake_queue: FakeRedis) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Bob (manager, has ingest) creates the job -> he is the owner.
        bob = await _login(client, "bob@demo.dev")
        response = await client.post(
            "/documents/ingest-async",
            files={"file": ("owner.md", b"# owner doc\ncontent here\n", "text/markdown")},
            headers={"Authorization": f"Bearer {bob}"},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        # Owner sees it.
        own = await client.get(
            f"/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {bob}"}
        )
        assert own.status_code == 200
        assert own.json()["status"] == "queued"

        # Carol (employee) is neither owner nor admin.
        carol = await _login(client, "carol@demo.dev")
        forbidden = await client.get(
            f"/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {carol}"}
        )
        assert forbidden.status_code == 403

        # Alice (administrator) may read any job.
        alice = await _login(client, "alice@demo.dev")
        allowed = await client.get(
            f"/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {alice}"}
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "queued"

        missing = await client.get(
            f"/documents/jobs/{job_id}-nope", headers={"Authorization": f"Bearer {bob}"}
        )
        assert missing.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_records_failed_jobs(_fake_queue: FakeRedis) -> None:
    """A job whose handler fails is marked failed with the error."""
    from scripts.worker import Worker

    # Hand-craft a job with invalid base64 - the handler fails permanently.
    payload = {
        "filename": "broken.md",
        "content_b64": "!!!not-base64!!!",
        "department": "general",
        "user": {"id": "00000000-0000-0000-0000-000000000000", "email": "a@b.c"},
    }
    job_id = await jobs.enqueue(_fake_queue, kind="ingest", payload=payload)

    worker = Worker()
    worker._client = _fake_queue
    job = await jobs.fetch_next(_fake_queue, kind="ingest", timeout=1)
    await worker._handle(job)

    failed = await jobs.get_job(_fake_queue, job_id)
    assert failed["status"] == "failed"
    assert "base64" in failed["error"].lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_rejects_unknown_job_kind(_fake_queue: FakeRedis) -> None:
    from scripts.worker import Worker

    job_id = await jobs.enqueue(_fake_queue, kind="telemetry", payload={})
    worker = Worker()
    worker._client = _fake_queue
    job = await jobs.fetch_next(_fake_queue, kind="ingest", timeout=1)
    # The telemetry job sits on its own queue; simulate a mis-dispatched
    # job object directly to exercise the guard.
    job = dict(job or {}, kind="telemetry", id=job_id)
    await worker._handle(job)
    failed = await jobs.get_job(_fake_queue, job_id)
    assert failed["status"] == "failed"
    assert "unknown job kind" in failed["error"]
