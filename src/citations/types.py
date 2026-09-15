"""Citation types — shared dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CitationResult:
    """A single citation in a generated answer."""

    chunk_id: str
    document_id: str
    document_title: str
    page: int | None
    section: str | None
    url: str | None
    snippet: str
    verified: bool
