"""Shared heuristics for location_cards summary quality (draft + semantic checks)."""

from __future__ import annotations

import re

from pipeline.generate.draft.prose_lint import (
    has_currently_meta,
    trim_words,
    word_count,
)

MIN_LOCATION_SUMMARY_WORDS = 20
MAX_LOCATION_SUMMARY_WORDS = 50

_GENERIC_FILLER_PATTERNS = (
    re.compile(r"\bis a (?:major )?(?:location|landmark|area|zone)\b", re.IGNORECASE),
    re.compile(r"\bis located in\b", re.IGNORECASE),
    re.compile(r"\bnotable place\b", re.IGNORECASE),
    re.compile(r"\bappears in this zone\b", re.IGNORECASE),
)

_FACTION_LEDE_RE = re.compile(
    r"\b(factions|quest giver|npc|reputation)\b|"
    r"\bis (?:a|an) .{0,40} faction\b",
    re.IGNORECASE,
)

_DATING_CONVENTION_RE = re.compile(
    r"\([^)]*\b(?:BCE|CE|ADP|BDP)\b[^)]*\)|\b\d+\s+(?:BCE|CE|AD)\b",
    re.IGNORECASE,
)


def ensure_sentence_terminator(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".?!":
        return cleaned
    return f"{cleaned}."


def trim_location_summary(text: str, max_words: int = MAX_LOCATION_SUMMARY_WORDS) -> str:
    return ensure_sentence_terminator(trim_words(text, max_words, ensure_terminal_punct=True))


def is_generic_location_summary(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    return any(pattern.search(cleaned) for pattern in _GENERIC_FILLER_PATTERNS)


def reads_like_faction_or_npc_lede(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if _FACTION_LEDE_RE.search(cleaned) and word_count(cleaned) < MIN_LOCATION_SUMMARY_WORDS + 8:
        return True
    return False


def has_zone_anchor(text: str, *, zone_name: str = "", location_name: str = "") -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if zone_name and zone_name.lower() in cleaned.lower():
        return True
    if location_name and re.search(rf"\b{re.escape(location_name)}\b", cleaned, re.IGNORECASE):
        return True
    return False


def lint_location_summary(
    text: str,
    *,
    zone_name: str = "",
    location_name: str = "",
) -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("location summary is empty")
        return issues
    words = word_count(cleaned)
    if words < MIN_LOCATION_SUMMARY_WORDS:
        issues.append(f"location summary below {MIN_LOCATION_SUMMARY_WORDS} words ({words})")
    if words > MAX_LOCATION_SUMMARY_WORDS:
        issues.append(f"location summary exceeds {MAX_LOCATION_SUMMARY_WORDS} words ({words})")
    if cleaned[-1] not in ".?!":
        issues.append("location summary does not end with sentence punctuation")
    if is_generic_location_summary(cleaned):
        issues.append("location summary reads like generic filler")
    if has_currently_meta(cleaned):
        issues.append("location summary contains reputation/achievement/player meta")
    if _DATING_CONVENTION_RE.search(cleaned):
        issues.append("location summary contains dating-convention framing")
    if reads_like_faction_or_npc_lede(cleaned):
        issues.append("location summary reads like faction or NPC lede")
    if zone_name and words >= MIN_LOCATION_SUMMARY_WORDS and not has_zone_anchor(
        cleaned, zone_name=zone_name, location_name=location_name
    ):
        issues.append("location summary lacks zone or landmark anchor")
    return issues


def fallback_location_summary(
    items: list[dict[str, object]],
    *,
    zone_name: str = "",
    location_name: str = "",
) -> tuple[str, list[str]]:
    ranked = sorted(items, key=lambda row: word_count(str(row.get("snippet", ""))), reverse=True)
    for item in ranked:
        snippet = trim_location_summary(str(item.get("snippet", "")))
        if snippet and not lint_location_summary(
            snippet,
            zone_name=zone_name,
            location_name=location_name,
        ):
            source_id = str(item.get("source_id", "")).strip()
            return snippet, [source_id] if source_id else []
    return "", []
