"""Lint helpers for questline and card hooks."""

from __future__ import annotations

import re

from pipeline.common.linguistics import tense_profile
from pipeline.generate.draft.prose_gate import (
    detect_midsentence_gap,
)
from pipeline.generate.draft.prose_lint import lint_adp_date_style, split_sentences, word_count

MAX_CTA_HOOK_WORDS = 36
_TRAILING_FRAGMENT_RE = re.compile(
    r"\b(and|or|but|with|for|to|the|a|an|in|on|at|of)\.?$", re.IGNORECASE
)
# A token-chop can land on a possessive/content word ("the Warchief's") that the stop-word
# list above misses; flag a trailing possessive with no following noun as truncated too.
_TRAILING_POSSESSIVE_RE = re.compile(r"\b[\w]+'s\.?$", re.IGNORECASE)
_MALFORMED_JOIN_RE = re.compile(
    r"\b(?:and|or|but)\s+(?:and|or|but)\b|[-–—]\s*(?:[,;:.!?]|$)",
    re.IGNORECASE,
)


def lint_cta_hook(text: str, *, forbidden_phrases: tuple[str, ...] = ()) -> list[str]:
    """Check the final CTA clause, not a pre-transform draft.

    CTA hooks are deliberately restricted to one complete declarative or imperative sentence.
    Sentence/clause features come from the repository linguistics wrapper; the remaining checks
    catch deterministic damage such as dangling function words and malformed joins.
    """
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
    sentences = split_sentences(cleaned)
    if len(sentences) != 1:
        issues.append("cta_hook must contain exactly one sentence")
    profile = tense_profile(cleaned)
    if not profile.imperative_like and profile.past_count + profile.present_count == 0:
        issues.append("cta_hook lacks a finite predicate or imperative structure")
    if _TRAILING_FRAGMENT_RE.search(cleaned) or _TRAILING_POSSESSIVE_RE.search(cleaned):
        issues.append("cta_hook looks truncated")
    if detect_midsentence_gap(cleaned):
        issues.append("cta_hook has a mid-sentence gap (dangling preposition/article)")
    if _MALFORMED_JOIN_RE.search(cleaned):
        issues.append("cta_hook has a malformed join")
    lowered = cleaned.casefold()
    for phrase in forbidden_phrases:
        normalized = phrase.strip().casefold()
        if normalized and normalized in lowered:
            issues.append("cta_hook repeats excluded outcome evidence")
            break
    issues.extend(lint_adp_date_style(cleaned))
    return issues


def finalize_cta_hook(text: str, *, max_words: int = MAX_CTA_HOOK_WORDS) -> str:
    cleaned = text.strip()
    if word_count(cleaned) <= max_words:
        return _repair_tail(cleaned)
    # Over budget: keep the longest run of *complete* sentences that fits the word cap,
    # rather than chopping the next sentence mid-clause (which produced "...the Warchief's.").
    kept: list[str] = []
    running = 0
    for sentence in split_sentences(cleaned):
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
