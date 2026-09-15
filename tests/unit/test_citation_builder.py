"""Unit tests for citation builder."""

from __future__ import annotations

from src.citations.builder import build_citations, parse_markers
from src.retrieval.types import ScoredChunk


def test_parse_markers():
    assert parse_markers("hello [1] world [2]") == [1, 2]
    assert parse_markers("[1][2][3]") == [1, 2, 3]
    assert parse_markers("no citations") == []
    assert parse_markers("[10] [20]") == [10, 20]


def test_build_citations():
    chunks = [
        ScoredChunk(
            chunk_id="c1",
            document_id="d1",
            document_title="Doc 1",
            content="Content of chunk 1",
            score=0.9,
            page=1,
            section="Intro",
        ),
        ScoredChunk(
            chunk_id="c2",
            document_id="d2",
            document_title="Doc 2",
            content="Content of chunk 2",
            score=0.8,
            page=2,
            section="Body",
        ),
    ]
    answer = "Claim one [1]. Claim two [2]."
    citations = build_citations(answer, chunks)

    assert len(citations) == 2
    assert citations[0].chunk_id == "c1"
    assert citations[0].page == 1
    assert citations[0].section == "Intro"
    assert citations[1].chunk_id == "c2"


def test_build_citations_out_of_range():
    chunks = [
        ScoredChunk(
            chunk_id="c1", document_id="d1", document_title="Doc 1", content="content", score=0.9
        ),
    ]
    answer = "Claim [1]. Out of range [2]."
    citations = build_citations(answer, chunks)
    assert len(citations) == 1
    assert citations[0].chunk_id == "c1"
