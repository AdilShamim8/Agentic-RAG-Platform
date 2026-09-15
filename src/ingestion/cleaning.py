"""Cleaning — normalize text, remove boilerplate."""

from __future__ import annotations

import re
import unicodedata


def clean(text: str) -> str:
    """Clean text: normalize unicode, strip whitespace, remove repeated boilerplate."""
    if not text:
        return ""

    # Unicode NFKC normalization
    text = unicodedata.normalize("NFKC", text)

    # Replace common PDF artifacts
    text = text.replace("\u00ad", "")  # soft hyphen
    text = re.sub(r"-\n", "", text)  # join hyphenated line breaks
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\r", "\n", text)

    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip leading/trailing whitespace per line
    text = "\n".join(line.strip() for line in text.split("\n"))

    return text.strip()


def remove_boilerplate(text: str, repeated_strings: set[str] | None = None) -> str:
    """Remove boilerplate headers/footers (heuristic: repeated strings across pages)."""
    if not repeated_strings:
        return text
    for s in repeated_strings:
        if len(s) > 20:  # only remove non-trivial repeated strings
            text = text.replace(s, "")
    return text
