"""Fetcher protocol + implementations (local, web, github)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class RawDocument:
    """A raw document from a source, before parsing."""

    source: str
    path_or_url: str
    content: bytes
    content_type: str  # pdf | md | html | docx | txt
    metadata: dict


class Fetcher(Protocol):
    async def fetch(self, source) -> AsyncIterator[RawDocument]: ...


class LocalFetcher:
    """Fetches files from a local directory."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    async def fetch(self, source) -> AsyncIterator[RawDocument]:
        for path in self.base_path.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".pdf", ".md", ".html", ".htm", ".docx", ".txt"}:
                continue
            content = path.read_bytes()
            content_type = path.suffix.lower().lstrip(".")
            yield RawDocument(
                source="local",
                path_or_url=str(path),
                content=content,
                content_type=content_type,
                metadata={"filename": path.name},
            )


class WebFetcher:
    """Fetches a URL with httpx + trafilatura."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def fetch(self, source) -> AsyncIterator[RawDocument]:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            yield RawDocument(
                source="web",
                path_or_url=self.url,
                content=response.content,
                content_type="html",
                metadata={"url": self.url, "status": response.status_code},
            )


class GitHubFetcher:
    """Fetches a directory from a GitHub repo via the API."""

    def __init__(self, repo: str, path: str = "") -> None:
        self.repo = repo
        self.path = path

    async def fetch(self, source) -> AsyncIterator[RawDocument]:
        # TODO: implement using github3 or PyGithub
        raise NotImplementedError("GitHub fetcher is a stub; see docs/learning/connectors.md")
