"""Ingestion script — `python -m scripts.ingest --source local --path data/sources/local/`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def main(
    source: str = typer.Option("local", help="Source type: local | web | github"),
    path: str = typer.Option(None, help="Path (for local)"),
    url: str = typer.Option(None, help="URL (for web)"),
    repo: str = typer.Option(None, help="Repo (for github: owner/repo)"),
    strategy: str = typer.Option("structure-aware", help="Chunking strategy"),
    department: str = typer.Option("general", help="Department slug"),
) -> None:
    """Ingest documents from a source."""
    asyncio.run(
        _ingest(
            source=source, path=path, url=url, repo=repo, strategy=strategy, department=department
        )
    )


async def _ingest(
    *,
    source: str,
    path: str | None,
    url: str | None,
    repo: str | None,
    strategy: str,
    department: str,
) -> None:
    from apps.api.app.core.db import session_scope
    from src.ingestion.chunking import get_chunker
    from src.ingestion.cleaning import clean
    from src.ingestion.fetchers import LocalFetcher, WebFetcher
    from src.ingestion.metadata import extract_metadata
    from src.ingestion.parsers import get_parser

    if source == "local":
        if not path:
            raise ValueError("--path is required for local source")
        fetcher = LocalFetcher(Path(path))
    elif source == "web":
        if not url:
            raise ValueError("--url is required for web source")
        fetcher = WebFetcher(url)
    elif source == "github":
        if not repo:
            raise ValueError("--repo is required for github source")
        raise NotImplementedError("GitHub fetcher not implemented")
    else:
        raise ValueError(f"Unknown source: {source}")

    chunker = get_chunker(strategy)
    count = 0

    async with session_scope() as _session:
        async for raw in fetcher.fetch(source=None):
            parser = get_parser(raw.content_type)
            parsed = parser.parse(raw)
            parsed.markdown_text = clean(parsed.markdown_text)
            _metadata = extract_metadata(parsed=parsed, raw=raw, department=department)
            chunks = chunker.chunk(parsed)
            # TODO: create/update Document, then call index_chunks
            count += len(chunks)
            print(
                f"Ingested {raw.metadata.get('filename', raw.path_or_url)} → {len(chunks)} chunks"
            )

    print(f"\nDone. Total chunks: {count}")


if __name__ == "__main__":
    app()
