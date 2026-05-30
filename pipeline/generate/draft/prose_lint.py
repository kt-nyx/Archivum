"""Shared heuristics for zone prose quality (draft + semantic checks)."""

from __future__ import annotations

import re
from typing import Any

from pipeline.discovery.world_registry import entry_kinds

_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
MAX_AT_A_GLANCE_WORDS = 45
MIN_HISTORY_SECTIONS = 3
MAX_HISTORY_SECTIONS = 8
AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD = 0.55
_SHORT_TEXT_PRESENT_CARVEOUT_WORDS = 8

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
    r"\b(was|were|had been|became|fell|destroyed|invaded|established|founded|consumed|overran|collapsed|remained)\b",
    re.IGNORECASE,
)

_PRESENT_TENSE_RE = re.compile(
    r"\b("
    r"is|are|remains|remain|continues|continue|stands|stand|holds|hold|"
    r"maintains|maintain|struggles|struggle|heals|heal|clashes|clash|patrols|patrol|"
    r"works|work|contests|contest|coordinates|coordinate|guards|guard"
    r")\b",
    re.IGNORECASE,
)

_LOCATION_LIST_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:'s)?(?:,\s*)?){3,}[A-Z][a-z]+",
)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def trim_words(text: str, max_words: int, *, ensure_terminal_punct: bool = False) -> str:
    words = text.split()
    if len(words) <= max_words:
        result = text.strip()
    else:
        result = " ".join(words[:max_words]).strip()
    if ensure_terminal_punct and result and result[-1] not in ".?!":
        return f"{result}."
    return result


def _token_set(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 4}


def token_jaccard_overlap(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def tense_marker_counts(text: str) -> tuple[int, int]:
    past = len(_PAST_TENSE_RE.findall(text))
    present = len(_PRESENT_TENSE_RE.findall(text))
    return past, present


def has_dominant_present_tense(text: str, *, short_text_word_limit: int = _SHORT_TEXT_PRESENT_CARVEOUT_WORDS) -> bool:
    past, present = tense_marker_counts(text)
    if present == 0:
        return False
    if past == 0 and word_count(text) < short_text_word_limit:
        return False
    return present > past or (present >= 1 and past == 0)


def past_marker_score(text: str) -> int:
    past, present = tense_marker_counts(text)
    return past * 2 - present


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
    if has_dominant_present_tense(text):
        issues.append("at_a_glance uses dominant present tense")
    if not _PAST_TENSE_RE.search(text) and not has_historical_framing(text):
        if words >= _SHORT_TEXT_PRESENT_CARVEOUT_WORDS:
            issues.append("at_a_glance lacks past-tense or historical framing")
    return issues


def lint_currently(text: str, *, zone_name: str = "", at_a_glance: str = "") -> list[str]:
    issues: list[str] = []
    if has_geography_hub_in_text(text):
        issues.append("currently mentions geography hub proper nouns")
    if has_currently_meta(text):
        issues.append("currently contains reputation/achievement/player meta")
    if at_a_glance.strip():
        overlap = token_jaccard_overlap(at_a_glance, text)
        if overlap >= AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD:
            issues.append("currently substantially overlaps at_a_glance")
    words = word_count(text)
    if words >= _SHORT_TEXT_PRESENT_CARVEOUT_WORDS and not _PRESENT_TENSE_RE.search(text):
        issues.append("currently lacks present-tense active-state framing")
    elif has_historical_framing(text) and not _PRESENT_TENSE_RE.search(text):
        issues.append("currently uses historical-era framing without present tense")
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
        has_framing = bool(_PAST_TENSE_RE.search(body)) or has_historical_framing(body)
        if not has_framing:
            issues.append(f"history_sections[{index}] lacks past-tense historical framing")
        elif has_dominant_present_tense(body, short_text_word_limit=0):
            issues.append(f"history_sections[{index}] uses dominant present tense")
    return issues


def validate_at_a_glance(text: str, *, zone_name: str = "") -> bool:
    return not lint_at_a_glance(text, zone_name=zone_name)


def validate_currently(text: str, *, zone_name: str = "", at_a_glance: str = "") -> bool:
    return not lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance)


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
