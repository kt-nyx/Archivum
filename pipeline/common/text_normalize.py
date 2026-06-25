"""Shared wiki text normalization helpers."""

from __future__ import annotations

import html
import re

_HTML_ENTITY_RE = re.compile(r"&#\d+;|&[a-zA-Z]+;")
_CITATION_RE = re.compile(r"\[\s*\d+\s*\]")
# Wiki lead pronunciation guides — e.g. "( /ˈskoʊ.loʊ.mæns/ SKOH-loh-mance )". The IPA
# carries non-Latin phonetic glyphs that trip the prose script-mixing gate (and are noise
# in lore prose), so strip the whole parenthetical. Keyed on the leading "/IPA/" slash
# block so ordinary parentheticals (even ones containing "/") are left intact.
_PRONUNCIATION_RE = re.compile(r"\(\s*/[^/()]*/[^)]*\)")
_WHITESPACE_RE = re.compile(r"\s+")
# Wiki inline-link stripping leaves a stray space before punctuation/possessives
# (e.g. "Third War ,", "Lordaeron 's"). Repair those here, the central choke point for
# all passthrough prose. Only spaces that *precede* the mark are removed, so decimals and
# ellipses (which have no preceding space) are untouched.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_SPACE_BEFORE_POSSESSIVE_RE = re.compile(r"\s+'(s\b|\s|$)")
# Some wiki dungeon/zone descriptions open with a source-attribution preface quoting an external
# page — e.g. "From the World Dungeons page on the official World of Warcraft Community Site:".
# That attribution is not lore and must never surface as prose (it leaked verbatim into a
# Scholomance overview). Strip a leading "From [the] ... <page/site/...> ... :" preface. Anchored
# to the page/site attribution words and bounded so it cannot swallow ordinary opening sentences.
_SOURCE_ATTRIBUTION_RE = re.compile(
    r"^From\s+(?:the\s+)?.{1,120}?\b(?:page|site|website|guide|manual|journal)\b.{0,120}?:\s*",
    re.IGNORECASE,
)


def clean_wiki_snippet(text: str) -> str:
    """Strip footnote markers, HTML entities, collapse whitespace, and fix link artifacts."""
    if not text:
        return ""
    decoded = html.unescape(text)
    decoded = _HTML_ENTITY_RE.sub(" ", decoded)
    decoded = _CITATION_RE.sub(" ", decoded)
    decoded = _PRONUNCIATION_RE.sub(" ", decoded)
    decoded = _WHITESPACE_RE.sub(" ", decoded)
    decoded = _SOURCE_ATTRIBUTION_RE.sub("", decoded)
    decoded = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", decoded)
    decoded = _SPACE_BEFORE_POSSESSIVE_RE.sub(r"'\1", decoded)
    return decoded.strip()
