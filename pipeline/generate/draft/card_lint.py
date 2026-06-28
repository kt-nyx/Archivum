"""Lint helpers for questline and card hooks."""

from __future__ import annotations

import re

from pipeline.generate.draft.prose_gate import (
    detect_dangling_terminal,
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
    if detect_midsentence_gap(cleaned):
        issues.append("cta_hook has a mid-sentence gap (dangling preposition/article)")
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


# Prepositions that can govern the zone name in a CTA ("march to <zone>", "fight in
# <zone>"). Longest-first so "toward"/"towards" win over "to" before the trailing \s+.
_CTA_ZONE_GOVERNORS = (
    "throughout",
    "towards",
    "without",
    "between",
    "against",
    "beneath",
    "besides",
    "through",
    "within",
    "across",
    "around",
    "toward",
    "beside",
    "amidst",
    "during",
    "onto",
    "unto",
    "upon",
    "amid",
    "over",
    "near",
    "into",
    "from",
    "with",
    "under",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
)


def strip_zone_name_from_cta(text: str, *, zone_name: str) -> str:
    """Remove a redundant zone-name mention from a questline cta_hook.

    Strips the zone name together with any function word that *governs* it — a leading
    preposition and/or article, or a coordinating conjunction when the zone is one of two
    coordinated objects — so removal never strands a dangling ``"to,"`` / ``"the and"`` gap
    (the two real Andorhal CTA defects). If stripping would still break the clause
    mid-sentence or leave a dangling terminal, the original (grammatical) hook is kept.
    """
    cleaned = text.strip()
    zone = zone_name.strip()
    if not cleaned or not zone:
        return cleaned
    pattern = re.compile(
        r"(?:\b(?P<prep>" + "|".join(_CTA_ZONE_GOVERNORS) + r")\s+)?"
        r"(?:\b(?P<art>the|a|an)\s+)?" + re.escape(zone) + r"(?:\s+(?P<conj>and|or)\b)?",
        re.IGNORECASE,
    )

    def _replace(match: re.Match[str]) -> str:
        # Keep a coordinating conjunction only when a preposition governed the zone — there
        # it joins clauses/verbs ("march to <zone> and reclaim" -> "march and reclaim").
        # With no preposition the conjunction joined two objects ("contest the <zone> and
        # every road" -> "contest every road"), so it is dropped with the zone phrase.
        conj = match.group("conj")
        if conj and match.group("prep"):
            return f" {conj} "
        return " "

    stripped = _tidy_cta_whitespace(pattern.sub(_replace, cleaned))
    if not word_count(stripped):
        return cleaned
    # Never trade a grammatical hook for a broken one: if the strip introduced a mid-sentence
    # gap or dangling terminal the original lacked, keep the original zone mention.
    if (detect_midsentence_gap(stripped) or detect_dangling_terminal(stripped)) and not (
        detect_midsentence_gap(cleaned) or detect_dangling_terminal(cleaned)
    ):
        return cleaned
    return stripped


def _tidy_cta_whitespace(text: str) -> str:
    cleaned = re.sub(r"\s{2,}", " ", text)
    cleaned = re.sub(r"\s+([,;.!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned
