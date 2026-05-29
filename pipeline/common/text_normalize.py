"""Shared wiki text normalization helpers."""

from __future__ import annotations

import html
import re

_HTML_ENTITY_RE = re.compile(r"&#\d+;|&[a-zA-Z]+;")
_CITATION_RE = re.compile(r"\[\s*\d+\s*\]")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_wiki_snippet(text: str) -> str:
    """Strip footnote markers, HTML entities, and collapse whitespace."""
    if not text:
        return ""
    decoded = html.unescape(text)
    decoded = _HTML_ENTITY_RE.sub(" ", decoded)
    decoded = _CITATION_RE.sub(" ", decoded)
    return _WHITESPACE_RE.sub(" ", decoded).strip()
