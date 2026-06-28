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

_DISPLAY_PUNCT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2026": "...",
    }
)

_NON_DISPLAY_STRING_KEYS = frozenset(
    {
        "id",
        "zone_id",
        "instance_id",
        "parent_zone_id",
        "term_id",
        "source_id",
        "source_ids",
        "revision_id",
        "revision_ids",
        "excerpt_hash",
        "url",
        "wiki_url",
        "wiki_ref",
        "wiki_refs",
        "source_url",
        "source_urls",
        "source_ref",
        "source_refs",
        "locator",
        "thumbnail_asset_id",
        "chain_refs",
        "source_link",
    }
)

_NON_DISPLAY_CONTAINER_KEYS = frozenset({"provenance", "sources"})


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


def normalize_display_punctuation(text: str) -> str:
    """Normalize generated display punctuation to ordinary typed ASCII forms."""
    if not text:
        return ""
    return text.translate(_DISPLAY_PUNCT_TRANSLATION)


def normalize_display_payload(value: object, *, key: str = "") -> object:
    """Recursively normalize only public display strings in a draft/build payload.

    IDs, URLs, hashes, revision/source metadata, and provenance/source manifests are left untouched
    so normalization never mutates references or raw evidence identifiers.
    """
    if isinstance(value, str):
        return value if key in _NON_DISPLAY_STRING_KEYS else normalize_display_punctuation(value)
    if isinstance(value, list):
        if key in _NON_DISPLAY_STRING_KEYS:
            return value
        return [normalize_display_payload(item) for item in value]
    if isinstance(value, dict):
        out: dict[object, object] = {}
        for child_key, child_value in value.items():
            child_key_str = str(child_key)
            if child_key_str in _NON_DISPLAY_CONTAINER_KEYS:
                out[child_key] = child_value
            else:
                out[child_key] = normalize_display_payload(child_value, key=child_key_str)
        return out
    return value
