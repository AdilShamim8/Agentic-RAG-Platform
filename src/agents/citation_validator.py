"""Citation validator — verifies that [N] markers map to chunks that support the claim."""

from __future__ import annotations

import re

from src.citations.types import CitationResult
from src.llm.provider import LLMProvider
from src.retrieval.types import ScoredChunk

CITATION_VERIFIER_PROMPT = """You are a citation verifier.

For each claim-citation pair, decide whether the cited chunk actually supports the claim.

Return JSON: {{"results": [{{"claim": "...", "chunk_id": "...", "supported": true|false}}]}}

CLAIMS:
{claims}

CHUNKS:
{chunks}
"""


async def validate_citations(
    answer: str, chunks: list[ScoredChunk], llm: LLMProvider
) -> list[CitationResult]:
    """Parse [N] markers from the answer, map to chunks, and verify each is supported."""
    # 1. Find all [N] markers in the answer
    markers = re.findall(r"\[(\d+)\]", answer)
    if not markers:
        return []

    # 2. Map markers to chunk indices (1-indexed)
    citations: list[CitationResult] = []
    for marker in markers:
        idx = int(marker) - 1
        if 0 <= idx < len(chunks):
            chunk = chunks[idx]
            citations.append(
                CitationResult(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    page=chunk.page,
                    section=chunk.section,
                    url=chunk.url,
                    snippet=chunk.content[:300],
                    verified=False,  # will be set below
                )
            )

    if not citations:
        return []

    # 3. Verify each citation via LLM-judge
    unique_chunks = {c.chunk_id: c for c in chunks}
    chunk_text = "\n\n".join(
        f"[chunk_id={cid}] {c.content[:300]}"
        for cid, c in unique_chunks.items()
        if c.chunk_id in {x.chunk_id for x in citations}
    )

    prompt = CITATION_VERIFIER_PROMPT.format(
        claims="\n".join(f"- {c.snippet[:200]}" for c in citations),
        chunks=chunk_text,
    )
    try:
        response = await llm.complete_json(prompt, temperature=0.0)
        results = {r["chunk_id"]: r["supported"] for r in response.get("results", [])}
    except Exception:
        results = {}

    # 4. Mark verified
    for c in citations:
        c.verified = results.get(c.chunk_id, False)

    # 5. If any citation is unverified, drop it (do not return unverifiable citations to the user)
    return [c for c in citations if c.verified]
