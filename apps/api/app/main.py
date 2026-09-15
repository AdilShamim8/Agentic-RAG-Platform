"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.core.config import settings
from apps.api.app.observability.logging import setup_logging
from apps.api.app.observability.metrics import setup_metrics
from apps.api.app.observability.otel import setup_otel
from apps.api.app.routers import (
    admin,
    auth,
    conversations,
    documents,
    evaluations,
    health,
    memory,
    query,
    search,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup + shutdown hooks."""
    setup_logging(log_level=settings.app_log_level)
    setup_otel(
        service_name=settings.otel_service_name, endpoint=settings.otel_exporter_otlp_endpoint
    )
    setup_metrics(app)
    # TODO: warm up embedder + reranker (download models if missing)
    yield
    # Shutdown


app = FastAPI(
    title="Agentic RAG Platform",
    description="Production-grade Agentic RAG API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(query.router, prefix="/query", tags=["query"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(evaluations.router, prefix="/evaluations", tags=["evaluations"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/")
async def root() -> dict:
    return {"name": "Agentic RAG Platform", "version": "1.0.0", "docs": "/docs"}
