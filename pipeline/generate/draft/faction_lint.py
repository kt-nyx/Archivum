"""Shared heuristics for major_factions card quality (draft + semantic checks)."""

from __future__ import annotations

import re

from pipeline.generate.draft.prose_lint import (
    has_currently_meta,
    has_historical_framing,
    trim_words,
    word_count,
)

MIN_FACTION_SUMMARY_WORDS = 12
MAX_FACTION_SUMMARY_WORDS = 40

_GENERIC_FILLER_PATTERNS = (
    re.compile(r"\bappears in this zone'?s active conflicts\b", re.IGNORECASE),
    re.compile(r"\bpolitical narrative\b", re.IGNORECASE),
    re.compile(r"\bactive conflicts and political\b", re.IGNORECASE),
    re.compile(r"\bis a .+ faction\b", re.IGNORECASE),
)

_PRESENT_ROLE_RE = re.compile(
    r"\b("
    r"is|are|remains|remain|continues|continue|holds|hold|operates|operate|controls|control|"
    r"maintains|maintain|coordinates|coordinate|patrols|patrol|guards|guard|"
    r"pushes|push|sends|send|defends|defend|occupies|occupy"
    r")\b",
    re.IGNORECASE,
)


def ensure_sentence_terminator(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".?!":
        return cleaned
    return f"{cleaned}."


def trim_faction_summary(text: str, max_words: int = MAX_FACTION_SUMMARY_WORDS) -> str:
    return ensure_sentence_terminator(trim_words(text, max_words, ensure_terminal_punct=True))


def is_generic_faction_summary(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    return any(pattern.search(cleaned) for pattern in _GENERIC_FILLER_PATTERNS)


def has_zone_role_framing(text: str) -> bool:
    return bool(_PRESENT_ROLE_RE.search(text)) or has_historical_framing(text)


def summary_has_zone_anchor(text: str, *, zone_name: str, subregion_tokens: list[str]) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if zone_name and zone_name.lower() in cleaned.lower():
        return True
    for token in subregion_tokens:
        if token and token.lower() in cleaned.lower():
            return True
    return False


def lint_faction_summary(
    text: str,
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("faction summary is empty")
        return issues
    words = word_count(cleaned)
    if words < MIN_FACTION_SUMMARY_WORDS:
        issues.append(f"faction summary below {MIN_FACTION_SUMMARY_WORDS} words ({words})")
    if words > MAX_FACTION_SUMMARY_WORDS:
        issues.append(f"faction summary exceeds {MAX_FACTION_SUMMARY_WORDS} words ({words})")
    if cleaned[-1] not in ".?!":
        issues.append("faction summary does not end with sentence punctuation")
    if is_generic_faction_summary(cleaned):
        issues.append("faction summary reads like generic filler")
    if has_currently_meta(cleaned):
        issues.append("faction summary contains reputation/achievement/player meta")
    if zone_name and zone_name.lower() in cleaned.lower() and words < MIN_FACTION_SUMMARY_WORDS:
        issues.append("faction summary reads like bare zone-description filler")
    if words >= MIN_FACTION_SUMMARY_WORDS and not has_zone_role_framing(cleaned):
        issues.append("faction summary lacks zone role framing")
    tokens = subregion_tokens or []
    if (
        zone_name
        and words >= MIN_FACTION_SUMMARY_WORDS
        and not summary_has_zone_anchor(
            cleaned,
            zone_name=zone_name,
            subregion_tokens=tokens,
        )
    ):
        issues.append("faction summary lacks zone or subregion anchor")
    return issues
