"""Shared wiki text normalization helpers."""

from __future__ import annotations

import html
import re

_HTML_ENTITY_RE = re.compile(r"&#\d+;|&[a-zA-Z]+;")
_CITATION_RE = re.compile(r"\[\s*\d+\s*\]")
_WHITESPACE_RE = re.compile(r"\s+")
# Wiki inline-link stripping leaves a stray space before punctuation/possessives
# (e.g. "Third War ,", "Lordaeron 's"). Repair those here, the central choke point for
# all passthrough prose. Only spaces that *precede* the mark are removed, so decimals and
# ellipses (which have no preceding space) are untouched.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_SPACE_BEFORE_POSSESSIVE_RE = re.compile(r"\s+'(s\b|\s|$)")


def clean_wiki_snippet(text: str) -> str:
    """Strip footnote markers, HTML entities, collapse whitespace, and fix link artifacts."""
    if not text:
        return ""
    decoded = html.unescape(text)
    decoded = _HTML_ENTITY_RE.sub(" ", decoded)
    decoded = _CITATION_RE.sub(" ", decoded)
    decoded = _WHITESPACE_RE.sub(" ", decoded)
    decoded = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", decoded)
    decoded = _SPACE_BEFORE_POSSESSIVE_RE.sub(r"'\1", decoded)
    return decoded.strip()
