"""Shared heuristics for zone instance_links card quality (draft + semantic checks)."""

from __future__ import annotations

import re

from pipeline.generate.draft.faction_lint import ensure_sentence_terminator
from pipeline.generate.draft.prose_lint import trim_words, word_count

MIN_INSTANCE_LINK_WORDS = 10
MAX_INSTANCE_LINK_WORDS = 35

_GENERIC_INSTANCE_LINK = re.compile(
    r"\banchors a key conflict thread linked to this zone\b",
    re.IGNORECASE,
)


def is_generic_instance_link_summary(text: str) -> bool:
    return bool(_GENERIC_INSTANCE_LINK.search(text.strip()))


def lint_instance_link_summary(
    text: str,
    *,
    instance_name: str,
    zone_name: str,
) -> list[str]:
    cleaned = text.strip()
    issues: list[str] = []
    if not cleaned:
        issues.append("instance link summary is empty")
        return issues
    if is_generic_instance_link_summary(cleaned):
        issues.append("instance link summary reads like generic stub filler")
    words = word_count(cleaned)
    if words < MIN_INSTANCE_LINK_WORDS:
        issues.append(
            f"instance link summary has {words} words; minimum is {MIN_INSTANCE_LINK_WORDS}"
        )
    if words > MAX_INSTANCE_LINK_WORDS:
        issues.append(
            f"instance link summary has {words} words; maximum is {MAX_INSTANCE_LINK_WORDS}"
        )
    if instance_name and instance_name.lower() not in cleaned.lower():
        issues.append(f"instance link summary must mention instance name {instance_name!r}")
    if cleaned[-1] not in ".?!":
        issues.append("instance link summary must end with sentence punctuation")
    return issues


def trim_instance_link_summary(text: str, max_words: int = MAX_INSTANCE_LINK_WORDS) -> str:
    return ensure_sentence_terminator(trim_words(text, max_words, ensure_terminal_punct=True))
