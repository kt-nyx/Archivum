"""Lint helpers for questline and card hooks."""

from __future__ import annotations

import re

from pipeline.generate.draft.prose_lint import trim_words, word_count

MAX_CTA_HOOK_WORDS = 35
_TRAILING_FRAGMENT_RE = re.compile(r"\b(and|or|but|with|for|to|the|a|an|in|on|at|of)\.?$", re.IGNORECASE)


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
    if _TRAILING_FRAGMENT_RE.search(cleaned):
        issues.append("cta_hook looks truncated")
    return issues


def finalize_cta_hook(text: str, *, max_words: int = MAX_CTA_HOOK_WORDS) -> str:
    trimmed = trim_words(text.strip(), max_words, ensure_terminal_punct=True)
    if trimmed and trimmed[-1] not in ".?!":
        trimmed = f"{trimmed}."
    return trimmed
