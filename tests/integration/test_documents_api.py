"""Document lifecycle API tests: ingest, list, get, versions, soft delete.

Runs against real PostgreSQL with the deterministic test embedder; RBAC and
freshness behavior covered in tests/security and tests/integration/test_freshness.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from apps.api.app.core.db import session_scope
from apps.api.app.main import app
from apps.api.app.models.audit import AuditLog
from apps.api.app.models.document import Document, DocumentChunk, DocumentVersion
from tests.helpers_seed import purge_docs

MARKDOWN = b"""# Remote Work Policy

Employees may work remotely up to 3 days per week under the current policy.
Remote work requests must be approved by the direct manager in advance.
"""


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def _cleanup_docs():
    """Remove any documents created by these tests (chunk + version cascade via FK)."""
    yield
    async with session_scope() as session:
        rows = await session.scalars(
            select(Document).where(Document.source_id.is_(None), Document.owner_id.is_not(None))
        )
        for doc in rows:
            if doc.doc_type in ("md", "txt", "pdf", "docx", "html"):
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
                )
                await session.execute(
                    delete(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                )
                await session.execute(delete(Document).where(Document.id == doc.id))
                await session.execute(delete(AuditLog).where(AuditLog.target == str(doc.id)))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_and_lifecycle() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")

        # 1. Ingest a markdown file
        response = await client.post(
            "/documents/ingest",
            files={"file": ("policy.md", MARKDOWN, "text/markdown")},
            params={"department": "hr"},
            headers=_auth(alice),
        )
        assert response.status_code == 200, response.text
        doc = response.json()
        assert doc["title"] == "Remote Work Policy"
        assert doc["doc_type"] == "md"
        assert doc["version"] == 1
        document_id = doc["id"]

        # 2. List contains it
        listing = await client.get("/documents", headers=_auth(alice))
        assert listing.status_code == 200
        assert any(d["id"] == document_id for d in listing.json())

        # 3. Detail has chunk count and effective window fields
        detail = await client.get(f"/documents/{document_id}", headers=_auth(alice))
        assert detail.status_code == 200
        body = detail.json()
        assert body["chunk_count"] >= 1
        assert body["source"] == "upload"
        assert "effective_from" in body and "access_policy" in body

        # 4. Version history
        versions = await client.get(f"/documents/{document_id}/versions", headers=_auth(alice))
        assert versions.status_code == 200
        assert versions.json()[0]["version"] == 1
        assert versions.json()[0]["change_summary"] == "initial ingest"

        # 5. Duplicate upload (same content) is idempotent - same document id
        again = await client.post(
            "/documents/ingest",
            files={"file": ("copy.md", MARKDOWN, "text/markdown")},
            headers=_auth(alice),
        )
        assert again.status_code == 200
        assert again.json()["id"] == document_id

        # 6. Soft delete
        deleted = await client.delete(f"/documents/{document_id}", headers=_auth(alice))
        assert deleted.status_code == 200

        # 7. After delete: 404 on get, absent from list
        resp = await client.get(f"/documents/{document_id}", headers=_auth(alice))
        assert resp.status_code == 404
        listing2 = await client.get("/documents", headers=_auth(alice))
        assert all(d["id"] != document_id for d in listing2.json())

        # 8. Audit log rows exist for ingest and delete
        async with session_scope() as session:
            logs = await session.scalars(select(AuditLog).where(AuditLog.target == document_id))
            actions = {log.action for log in logs}
        assert {"document.ingest", "document.delete"} <= actions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_permission_denied_for_employee() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        carol = await _login(client, "carol@demo.dev")
        response = await client.post(
            "/documents/ingest",
            files={"file": ("policy.md", MARKDOWN, "text/markdown")},
            headers=_auth(carol),
        )
        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_rejects_bad_files() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")

        # Unsupported extension
        exe = await client.post(
            "/documents/ingest",
            files={"file": ("malware.exe", b"payload", "application/octet-stream")},
            headers=_auth(alice),
        )
        assert exe.status_code == 400

        # Empty file
        empty = await client.post(
            "/documents/ingest",
            files={"file": ("empty.md", b"", "text/markdown")},
            headers=_auth(alice),
        )
        assert empty.status_code == 400

        # Mislabeled PDF (extension says pdf, content is text)
        fake_pdf = await client.post(
            "/documents/ingest",
            files={"file": ("fake.pdf", b"just some plain text", "application/pdf")},
            headers=_auth(alice),
        )
        assert fake_pdf.status_code == 400

        # Oversized upload (over 20 MB)
        big = b"x" * (21 * 1024 * 1024)
        oversize = await client.post(
            "/documents/ingest",
            files={"file": ("big.md", big[: len(big)], "text/markdown")},
            headers=_auth(alice),
        )
        assert oversize.status_code == 413


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_document_authorization() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bob = await _login(client, "bob@demo.dev")
        carol = await _login(client, "carol@demo.dev")

        ingest = await client.post(
            "/documents/ingest",
            files={"file": ("policy.md", MARKDOWN, "text/markdown")},
            headers=_auth(bob),
        )
        doc_id = ingest.json()["id"]

        # Restrict the doc to managers (and admins) directly in the DB
        async with session_scope() as session:
            db_doc = await session.get(Document, doc_id)
            db_doc.access_policy = {"roles": ["manager", "administrator"]}

        # Employee (carol) cannot view, list, version, or delete it
        carol_view = await client.get(f"/documents/{doc_id}", headers=_auth(carol))
        assert carol_view.status_code == 403
        listing = await client.get("/documents", headers=_auth(carol))
        assert all(d["id"] != doc_id for d in listing.json())
        carol_versions = await client.get(f"/documents/{doc_id}/versions", headers=_auth(carol))
        assert carol_versions.status_code == 403
        carol_delete = await client.delete(f"/documents/{doc_id}", headers=_auth(carol))
        assert carol_delete.status_code == 403

        # Manager (bob) still can; delete is limited to write:document holders
        bob_view = await client.get(f"/documents/{doc_id}", headers=_auth(bob))
        assert bob_view.status_code == 200
        # eve (student) cannot delete; bob (manager) can
        eve = await _login(client, "eve@demo.dev")
        eve_delete = await client.delete(f"/documents/{doc_id}", headers=_auth(eve))
        assert eve_delete.status_code == 403
        bob_delete = await client.delete(f"/documents/{doc_id}", headers=_auth(bob))
        assert bob_delete.status_code == 200

        await purge_docs(doc_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_document_404() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        missing = await client.get(
            "/documents/00000000-0000-0000-0000-000000000dead", headers=_auth(alice)
        )
        assert missing.status_code == 404
        invalid = await client.get("/documents/not-a-uuid", headers=_auth(alice))
        assert invalid.status_code == 404
