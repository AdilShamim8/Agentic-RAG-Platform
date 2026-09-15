"""Chunking strategies — fixed, sliding, semantic, structure-aware."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import tiktoken


@dataclass(slots=True)
class Chunk:
    content: str
    chunk_index: int
    page: int | None
    section: str | None
    token_count: int
    content_hash: str


class Chunker(Protocol):
    def chunk(self, parsed) -> list[Chunk]: ...


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


class FixedTokenChunker:
    """Strategy A — fixed-size token chunks with overlap."""

    def __init__(self, size: int = 512, overlap: int = 64) -> None:
        self.size = size
        self.overlap = overlap

    def chunk(self, parsed) -> list[Chunk]:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(parsed.markdown_text)
        chunks = []
        idx = 0
        start = 0
        while start < len(tokens):
            end = min(start + self.size, len(tokens))
            chunk_tokens = tokens[start:end]
            text = enc.decode(chunk_tokens)
            chunks.append(
                Chunk(
                    content=text,
                    chunk_index=idx,
                    page=None,
                    section=None,
                    token_count=len(chunk_tokens),
                    content_hash=_hash(text),
                )
            )
            idx += 1
            if end >= len(tokens):
                break
            start = end - self.overlap
        return chunks


class SlidingWindowChunker:
    """Strategy B — sliding window with stride."""

    def __init__(self, size: int = 512, stride: int = 384) -> None:
        self.size = size
        self.stride = stride

    def chunk(self, parsed) -> list[Chunk]:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(parsed.markdown_text)
        chunks = []
        idx = 0
        start = 0
        while start < len(tokens):
            end = min(start + self.size, len(tokens))
            chunk_tokens = tokens[start:end]
            text = enc.decode(chunk_tokens)
            chunks.append(
                Chunk(
                    content=text,
                    chunk_index=idx,
                    page=None,
                    section=None,
                    token_count=len(chunk_tokens),
                    content_hash=_hash(text),
                )
            )
            idx += 1
            if end >= len(tokens):
                break
            start += self.stride
        return chunks


class SemanticChunker:
    """Strategy C — semantic chunking based on sentence embedding similarity.

    Breaks at points where adjacent sentences are semantically dissimilar.
    """

    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    def chunk(self, parsed) -> list[Chunk]:
        # TODO: implement using sentence-transformers
        # For now, fall back to sentence-based chunking
        import re

        sentences = re.split(r"(?<=[.!?])\s+", parsed.markdown_text)
        chunks = []
        for idx, sentence in enumerate(sentences):
            chunks.append(
                Chunk(
                    content=sentence,
                    chunk_index=idx,
                    page=None,
                    section=None,
                    token_count=_count_tokens(sentence),
                    content_hash=_hash(sentence),
                )
            )
        return chunks


class StructureAwareChunker:
    """Strategy D — splits on headings first, then fixed-token within a section."""

    def __init__(self, size: int = 512, overlap: int = 64) -> None:
        self.size = size
        self.overlap = overlap
        self._fixed = FixedTokenChunker(size=size, overlap=overlap)

    def chunk(self, parsed) -> list[Chunk]:
        if not parsed.sections:
            return self._fixed.chunk(parsed)

        chunks = []
        idx = 0
        for section in parsed.sections:
            section_chunks = self._fixed.chunk(type("P", (), {"markdown_text": section.content})())
            for c in section_chunks:
                c.chunk_index = idx
                c.section = section.title
                chunks.append(c)
                idx += 1
        return chunks


def get_chunker(strategy: str) -> Chunker:
    if strategy == "fixed":
        return FixedTokenChunker()
    if strategy == "sliding":
        return SlidingWindowChunker()
    if strategy == "semantic":
        return SemanticChunker()
    if strategy == "structure-aware":
        return StructureAwareChunker()
    raise ValueError(f"Unknown chunking strategy: {strategy}")
