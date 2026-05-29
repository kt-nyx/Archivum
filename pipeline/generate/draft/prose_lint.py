"""Shared heuristics for zone prose quality (draft + semantic checks)."""

from __future__ import annotations

import re
from typing import Any

from pipeline.discovery.world_registry import entry_kinds

_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
MAX_AT_A_GLANCE_WORDS = 45
MIN_HISTORY_SECTIONS = 3
MAX_HISTORY_SECTIONS = 8

_HISTORICAL_MARKERS = (
    "formerly",
    "once",
    "during the third war",
    "in the third war",
    "years ago",
    "before the cataclysm",
    "after the fall",
    "historically",
    "was founded",
    "was established",
    "invasion of",
)

_CURRENTLY_META_RE = re.compile(
    r"\breputation with\b|\bachievement\b|\bplayers can\b|\bbreadcrumb\b",
    re.IGNORECASE,
)

_PAST_TENSE_RE = re.compile(
    r"\b(was|were|had been|became|fell|destroyed|invaded|established|founded)\b",
    re.IGNORECASE,
)

_PRESENT_TENSE_RE = re.compile(
    r"\b(is|are|remains|remain|continues|continue|stands|stand|holds|hold)\b",
    re.IGNORECASE,
)

_LOCATION_LIST_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:'s)?(?:,\s*)?){3,}[A-Z][a-z]+",
)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()


def has_historical_framing(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _HISTORICAL_MARKERS)


def has_currently_meta(text: str) -> bool:
    return bool(_CURRENTLY_META_RE.search(text))


def has_geography_hub_in_text(text: str) -> bool:
    for token in re.findall(r"[A-Z][a-z]+(?:[''][a-z]+)?(?:\s+[A-Z][a-z]+)*", text):
        if entry_kinds(token.strip()) & _GEOGRAPHY_KINDS:
            return True
    return False


def has_location_list_dump(text: str) -> bool:
    if _LOCATION_LIST_RE.search(text):
        return True
    geography_hits = sum(1 for token in re.findall(r"\b[A-Z][a-z]+\b", text) if entry_kinds(token) & _GEOGRAPHY_KINDS)
    return geography_hits >= 4


def lint_at_a_glance(text: str, *, zone_name: str = "") -> list[str]:
    issues: list[str] = []
    words = word_count(text)
    if words > MAX_AT_A_GLANCE_WORDS:
        issues.append(f"at_a_glance exceeds {MAX_AT_A_GLANCE_WORDS} words ({words})")
    if has_location_list_dump(text):
        issues.append("at_a_glance reads like a location list dump")
    if zone_name and zone_name.lower() in text.lower() and words < 12:
        issues.append("at_a_glance reads like bare zone description filler")
    return issues


def lint_currently(text: str, *, zone_name: str = "") -> list[str]:
    issues: list[str] = []
    if has_geography_hub_in_text(text):
        issues.append("currently mentions geography hub proper nouns")
    if has_currently_meta(text):
        issues.append("currently contains reputation/achievement/player meta")
    if has_historical_framing(text) and not _PRESENT_TENSE_RE.search(text):
        issues.append("currently uses historical-era framing without present tense")
    if zone_name and has_historical_framing(text) and zone_name.lower() not in text.lower():
        issues.append("currently appears past-tense framed")
    return issues


def lint_history_sections(
    sections: list[dict[str, Any]],
    *,
    max_sections: int = MAX_HISTORY_SECTIONS,
) -> list[str]:
    issues: list[str] = []
    if len(sections) > max_sections:
        issues.append(f"history_sections count {len(sections)} exceeds cap {max_sections}")
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        body = str(section.get("body", "")).strip()
        if not body:
            issues.append(f"history_sections[{index}] has empty body")
            continue
        if not _PAST_TENSE_RE.search(body) and not has_historical_framing(body):
            issues.append(f"history_sections[{index}] lacks past-tense historical framing")
    return issues


def validate_at_a_glance(text: str, *, zone_name: str = "") -> bool:
    return not lint_at_a_glance(text, zone_name=zone_name)


def validate_currently(text: str, *, zone_name: str = "") -> bool:
    return not lint_currently(text, zone_name=zone_name)


def validate_history_sections(
    sections: list[dict[str, Any]],
    *,
    max_sections: int = MAX_HISTORY_SECTIONS,
    min_sections: int = 0,
) -> bool:
    issues = lint_history_sections(sections, max_sections=max_sections)
    if min_sections and len(sections) < min_sections:
        return False
    return not issues
