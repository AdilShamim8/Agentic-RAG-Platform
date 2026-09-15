"""Parsers — convert raw bytes to markdown + structured sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ParsedSection:
    title: str
    content: str
    level: int  # heading level (1=H1)


@dataclass
class ParsedDocument:
    markdown_text: str
    sections: list[ParsedSection]
    page_map: dict[int, str]  # page number → text (for PDFs)
    metadata: dict


class Parser(Protocol):
    def parse(self, raw) -> ParsedDocument: ...


class MarkdownParser:
    """Parses markdown — preserves headings as sections."""

    def parse(self, raw) -> ParsedDocument:
        text = raw.content.decode("utf-8", errors="replace")
        import re

        sections = []
        current_title = ""
        current_level = 0
        current_content: list[str] = []

        for line in text.split("\n"):
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                if current_title:
                    sections.append(
                        ParsedSection(
                            title=current_title,
                            content="\n".join(current_content),
                            level=current_level,
                        )
                    )
                current_level = len(m.group(1))
                current_title = m.group(2)
                current_content = []
            else:
                current_content.append(line)

        if current_title:
            sections.append(
                ParsedSection(
                    title=current_title,
                    content="\n".join(current_content),
                    level=current_level,
                )
            )

        return ParsedDocument(
            markdown_text=text,
            sections=sections,
            page_map={},
            metadata=raw.metadata,
        )


class HTMLParser:
    """Parses HTML using trafilatura (cleaner than raw BeautifulSoup)."""

    def parse(self, raw) -> ParsedDocument:
        import trafilatura

        text = (
            trafilatura.extract(
                raw.content.decode("utf-8", errors="replace"), output_format="markdown"
            )
            or ""
        )
        return ParsedDocument(
            markdown_text=text,
            sections=[],
            page_map={},
            metadata=raw.metadata,
        )


class PDFParser:
    """Parses PDF using docling (layout-aware)."""

    def parse(self, raw) -> ParsedDocument:
        # TODO: implement using docling
        # For now, use a fallback text extraction
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw.content))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
            page_map = {i: (page.extract_text() or "") for i, page in enumerate(reader.pages, 1)}
        except ImportError:
            text = "[PDF parsing requires `pip install docling`]"
            page_map = {}
        return ParsedDocument(
            markdown_text=text,
            sections=[],
            page_map=page_map,
            metadata=raw.metadata,
        )


class DOCXParser:
    """Parses DOCX using python-docx."""

    def parse(self, raw) -> ParsedDocument:
        import io

        from docx import Document

        doc = Document(io.BytesIO(raw.content))
        text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return ParsedDocument(
            markdown_text=text,
            sections=[],
            page_map={},
            metadata=raw.metadata,
        )


def get_parser(content_type: str) -> Parser:
    if content_type == "md":
        return MarkdownParser()
    if content_type in ("html", "htm"):
        return HTMLParser()
    if content_type == "pdf":
        return PDFParser()
    if content_type == "docx":
        return DOCXParser()
    if content_type == "txt":
        return MarkdownParser()  # treat as markdown
    raise ValueError(f"Unknown content type: {content_type}")
