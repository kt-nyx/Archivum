"""Lint helpers for questline and card hooks."""

from __future__ import annotations

import re

from pipeline.generate.draft.prose_lint import word_count

MAX_CTA_HOOK_WORDS = 35
_TRAILING_FRAGMENT_RE = re.compile(
    r"\b(and|or|but|with|for|to|the|a|an|in|on|at|of)\.?$", re.IGNORECASE
)
# A token-chop can land on a possessive/content word ("the Warchief's") that the stop-word
# list above misses; flag a trailing possessive with no following noun as truncated too.
_TRAILING_POSSESSIVE_RE = re.compile(r"\b[\w]+'s\.?$", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")


def lint_cta_hook(text: str) -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("cta_hook is empty")
        return issues
    words = word_count(cleaned)
    if words > MAX_CTA_HOOK_WORDS:
        issues.append(f"cta_hook exceeds {MAX_CTA_HOOK_WORDS} words ({words})")
    if cleaned[-1] not in ".?!":
        issues.append("cta_hook does not end with sentence punctuation")
    if _TRAILING_FRAGMENT_RE.search(cleaned) or _TRAILING_POSSESSIVE_RE.search(cleaned):
        issues.append("cta_hook looks truncated")
    return issues


def finalize_cta_hook(text: str, *, max_words: int = MAX_CTA_HOOK_WORDS) -> str:
    cleaned = text.strip()
    if word_count(cleaned) <= max_words:
        return _repair_tail(cleaned)
    # Over budget: keep the longest run of *complete* sentences that fits the word cap,
    # rather than chopping the next sentence mid-clause (which produced "...the Warchief's.").
    kept: list[str] = []
    running = 0
    for sentence in _SENTENCE_SPLIT_RE.split(cleaned):
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_words = word_count(sentence)
        if kept and running + sentence_words > max_words:
            break
        kept.append(sentence)
        running += sentence_words
    if kept:
        return _repair_tail(" ".join(kept))
    # No sentence boundary fits the cap (one long run-on) — hard token-trim and repair tail.
    trimmed_tokens: list[str] = []
    for match in re.finditer(r"\b[\w']+\b", cleaned):
        if len(trimmed_tokens) >= max_words:
            break
        trimmed_tokens.append(match.group(0))
    return _repair_tail(" ".join(trimmed_tokens))


def _repair_tail(text: str) -> str:
    """Drop a dangling trailing function word and ensure terminal sentence punctuation."""
    cleaned = _TRAILING_FRAGMENT_RE.sub(".", text.strip()).strip()
    if cleaned and cleaned[-1] not in ".?!":
        cleaned = f"{cleaned}."
    return cleaned


def strip_zone_name_from_cta(text: str, *, zone_name: str) -> str:
    """Remove bare zone-name filler from questline cta_hook prose."""
    cleaned = text.strip()
    if not cleaned or not zone_name.strip():
        return cleaned
    pattern = re.compile(re.escape(zone_name.strip()), re.IGNORECASE)
    stripped = pattern.sub("", cleaned)
    stripped = re.sub(r"\s{2,}", " ", stripped)
    stripped = re.sub(r"\s+,", ",", stripped)
    stripped = re.sub(r"\(\s*\)", "", stripped)
    stripped = re.sub(
        r"\bin the\s+(?=and\b|where\b|to\b|help\b)", " ", stripped, flags=re.IGNORECASE
    )
    stripped = re.sub(r"\s+\.", ".", stripped)
    return stripped.strip(" ,;")
