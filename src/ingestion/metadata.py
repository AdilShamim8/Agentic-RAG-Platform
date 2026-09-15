"""Metadata extraction — pulls structured metadata from raw + parsed documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class DocumentMetadata:
    document_id: str
    source: str
    title: str
    url: str | None
    doc_type: str
    department: str
    owner_id: str | None
    access_policy: dict
    created_at: datetime
    modified_at: datetime
    version: int
    effective_from: date | None
    effective_to: date | None


def content_hash(text: str) -> str:
    """SHA-256 of normalized text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_title(parsed, raw) -> str:
    """Heuristic title extraction."""
    if parsed.sections and parsed.sections[0].title:
        return parsed.sections[0].title[:255]
    if "filename" in raw.metadata:
        return raw.metadata["filename"]
    if "url" in raw.metadata:
        return raw.metadata["url"].split("/")[-1][:255]
    return "Untitled"


def extract_metadata(
    *, parsed, raw, department: str = "general", access_policy: dict | None = None
) -> DocumentMetadata:
    """Extract structured metadata from a parsed document."""
    title = extract_title(parsed, raw)
    return DocumentMetadata(
        document_id=content_hash(parsed.markdown_text)[:36],  # use content hash as ID seed
        source=raw.source,
        title=title,
        url=raw.metadata.get("url"),
        doc_type=raw.content_type,
        department=department,
        owner_id=None,
        access_policy=access_policy or {},
        created_at=datetime.utcnow(),
        modified_at=datetime.utcnow(),
        version=1,
        effective_from=None,
        effective_to=None,
    )
