"""Shared API schemas.

Lives outside the routers so services can import response models WITHOUT
creating service<->router import cycles (previously
query_service imported routers.query which imported query_service back;
importing the orchestrator first raised
"cannot import name 'run_agentic_query' from partially initialized module").
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# --- Query ----------------------------------------------------------------


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page: int | None = None
    section: str | None = None
    url: str | None = None
    snippet: str = Field(..., description="The text span from the chunk that supports the claim")
    verified: bool


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    conversation_id: str | None = None
    retrieval_strategy: str = "hybrid_reranked"  # dense | lexical | hybrid | hybrid_reranked
    top_k: int | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace_id: str
    conversation_id: str
    confidence: str  # low | medium | high
    failure: str | None = None
    metadata: dict = Field(default_factory=dict)


# --- Search ----------------------------------------------------------------


class ScoredChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    score: float
    page: int | None = None
    section: str | None = None
    url: str | None = None
    version: int
    effective_from: str | None = None
    effective_to: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    strategy: str = "hybrid_reranked"  # dense | lexical | hybrid | hybrid_reranked
    top_k: int = 10
    candidate_count: int = 50
    filters: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[ScoredChunk]
    trace_id: str
    latency_ms: int


# --- Documents ----------------------------------------------------------------


class DocumentOut(BaseModel):
    id: str
    title: str
    doc_type: str
    department: str | None
    owner_id: str | None
    version: int
    content_hash: str
    created_at: str
    updated_at: str


class DocumentDetail(DocumentOut):
    access_policy: dict
    effective_from: str | None
    effective_to: str | None
    source: str
    chunk_count: int
