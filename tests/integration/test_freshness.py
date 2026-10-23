"""Freshness / effective-date semantics — integration tests on real PostgreSQL.

Contract (src/retrieval/freshness.py):
- Default retrieval: only currently-effective documents (effective window
  covers today). Future-dated and expired documents are excluded in SQL,
  for every strategy.
- Explicit range (search_by_date filters): interval intersection, so
  historical queries can see superseded versions.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.api.app.core.db import session_scope
from apps.api.app.deps.auth import AuthUser
from src.retrieval.dense import dense_retrieve
from src.retrieval.engine import retrieve
from src.retrieval.freshness import effective_window_sql, is_currently_effective, parse_date_filters
from src.retrieval.lexical import lexical_retrieve
from src.retrieval.types import ScoredChunk
from tests.helpers_seed import purge_docs, seed_doc

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def _employee() -> AuthUser:
    return AuthUser(
        id="00000000-0000-0000-0000-000000000001",
        email="employee@demo.dev",
        name="Employee",
        role_slug="employee",
        permissions=frozenset(["read:document"]),
        projects=frozenset(),
        departments=frozenset(),
    )


def _chunk(document_id: str, **kwargs) -> ScoredChunk:
    base = {
        "chunk_id": "c",
        "document_id": document_id,
        "document_title": "t",
        "content": "x",
        "score": 1.0,
    }
    base.update(kwargs)
    return ScoredChunk(**base)


@pytest.fixture()
async def freshness_docs():
    """Seed current / expired / future documents and clean them up."""
    current = await seed_doc(
        title="Current Travel Policy",
        content="The per diem rate is $75 per day for domestic travel.",
        effective_from=YESTERDAY,
        effective_to=TOMORROW,
    )
    expired = await seed_doc(
        title="Old Travel Policy",
        content="The per diem rate was $50 per day for domestic travel.",
        effective_from=date(2020, 1, 1),
        effective_to=YESTERDAY,
    )
    future = await seed_doc(
        title="Future Travel Policy",
        content="The per diem rate will be $100 per day for domestic travel.",
        effective_from=TOMORROW,
        effective_to=None,
    )
    seeded = [current, expired, future]
    try:
        yield {"current": current, "expired": expired, "future": future}
    finally:
        for doc in seeded:
            await purge_docs(doc.document_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_default_retrieval_excludes_expired_and_future(freshness_docs) -> None:
    query = "What is the per diem rate for domestic travel?"
    user = _employee()
    async with session_scope() as session:
        for strategy in ("dense", "lexical", "hybrid"):
            chunks = await retrieve(
                query=query, user=user, session=session, strategy=strategy, top_k=10
            )
            ids = {c.document_id for c in chunks}
            assert freshness_docs["current"].document_id in ids, f"{strategy}: missing current"
            assert freshness_docs["expired"].document_id not in ids, f"{strategy}: expired leaked"
            assert freshness_docs["future"].document_id not in ids, f"{strategy}: future leaked"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_range_query_includes_expired_via_intersection(freshness_docs) -> None:
    """A historical range must be able to see the superseded (expired) version.

    Note: the range must end before the current doc's effective_from, otherwise
    the two windows overlap on the boundary day and interval-intersection
    semantics correctly includes both.
    """
    user = _employee()
    filters = {
        "effective_from_gte": date(2020, 1, 1),
        "effective_to_lte": TODAY - timedelta(days=2),
    }
    async with session_scope() as session:
        chunks = await lexical_retrieve(
            query="What was the per diem rate for domestic travel?",
            user=user,
            session=session,
            top_k=10,
            filters=filters,
        )
    ids = {c.document_id for c in chunks}
    assert freshness_docs["expired"].document_id in ids, "historical range lost the old version"
    assert freshness_docs["current"].document_id not in ids
    assert freshness_docs["future"].document_id not in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_range_query_includes_future_when_range_covers_it(freshness_docs) -> None:
    user = _employee()
    filters = {
        "effective_from_gte": TODAY + timedelta(days=2),
        "effective_to_lte": TODAY + timedelta(days=365),
    }
    async with session_scope() as session:
        chunks = await lexical_retrieve(
            query="What will the per diem rate be for domestic travel?",
            user=user,
            session=session,
            top_k=10,
            filters=filters,
        )
    ids = {c.document_id for c in chunks}
    assert freshness_docs["future"].document_id in ids
    assert freshness_docs["current"].document_id not in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_open_ended_window_matches_every_range(freshness_docs) -> None:
    """A doc with effective_to=null is visible in any historical range."""
    user = _employee()
    filters = {"effective_from_gte": date(2021, 1, 1), "effective_to_lte": date(2021, 12, 31)}
    # current doc: effective_from=YESTERDAY effective_to=TOMORROW -> does NOT
    # intersect 2021, so it must be excluded; expired (2020->yesterday) does.
    async with session_scope() as session:
        chunks = await lexical_retrieve(
            query="per diem rate domestic travel",
            user=user,
            session=session,
            top_k=10,
            filters=filters,
        )
    ids = {c.document_id for c in chunks}
    assert freshness_docs["expired"].document_id in ids
    assert freshness_docs["current"].document_id not in ids


def test_effective_window_sql_default_fragment() -> None:
    frag, params = effective_window_sql(None)
    assert "CURRENT_DATE" in frag
    assert params == {}
    assert "effective_from" in frag and "effective_to" in frag


def test_effective_window_sql_range_fragment() -> None:
    frag, params = effective_window_sql(
        {"effective_from_gte": "2024-01-01", "effective_to_lte": "2024-12-31"}
    )
    assert ":eff_from" in frag and ":eff_to" in frag
    assert params == {"eff_from": date(2024, 1, 1), "eff_to": date(2024, 12, 31)}


def test_parse_date_filters_handles_iso_strings_and_none() -> None:
    assert parse_date_filters({"effective_from_gte": "2024-05-01"}) == (date(2024, 5, 1), None)
    assert parse_date_filters({}) == (None, None)
    assert parse_date_filters(None) == (None, None)


def test_is_currently_effective_boundaries() -> None:
    today = date(2025, 6, 15)
    assert is_currently_effective(_chunk("d", effective_from=today, effective_to=today), today)
    assert not is_currently_effective(_chunk("d", effective_from=today + timedelta(days=1)), today)
    assert not is_currently_effective(_chunk("d", effective_to=today - timedelta(days=1)), today)
    assert is_currently_effective(_chunk("d"), today)  # open window


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dense_retrieval_uses_window_predicate(freshness_docs) -> None:
    """Direct dense adapter check: expired/future documents never returned."""
    user = _employee()
    async with session_scope() as session:
        chunks = await dense_retrieve(
            query="per diem rate for domestic travel", user=user, session=session, top_k=10
        )
    ids = {c.document_id for c in chunks}
    assert freshness_docs["current"].document_id in ids
    assert freshness_docs["expired"].document_id not in ids
    assert freshness_docs["future"].document_id not in ids
