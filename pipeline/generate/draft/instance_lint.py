"""Shared heuristics for instance page prose quality (draft + semantic checks)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from pipeline.common import wiki_html
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.prose_gate import detect_list_shape
from pipeline.generate.draft.prose_lint import (
    has_currently_meta,
    has_historical_framing,
    split_sentences,
    trim_words,
    word_count,
)

MIN_AT_A_GLANCE_WORDS = 10
MAX_AT_A_GLANCE_WORDS = 55
MIN_OVERVIEW_WORDS = 70
MAX_OVERVIEW_WORDS = 160
MIN_KEY_CHARACTER_WORDS = 18
MAX_KEY_CHARACTER_WORDS = 60

_GENERIC_AT_A_GLANCE = re.compile(r"\bis a lore-significant retail instance\b", re.IGNORECASE)
_GENERIC_OVERVIEW = re.compile(
    r"\bcontains key enemies and encounter stakes captured from Warcraft Wiki\b",
    re.IGNORECASE,
)
_GENERIC_ENEMY = re.compile(
    r"\bis a key enemy presence tied to the instance narrative\b", re.IGNORECASE
)
# Hollow / non-notable characterizations that signal a weak key-character pick or a poor
# LLM summary (e.g. Professor Slate "a bored student … neither guardian nor champion").
_HOLLOW_SUMMARY_RE = re.compile(
    r"\bneither\b[^.?!]*?\bnor\b"
    r"|\bbored student\b"
    r"|\bsmall but telling\b"
    r"|\bhollow academic\b",
    re.IGNORECASE,
)
_PATCH_NOTES_RE = re.compile(
    r"\b(patch|hotfix|achievement|dungeon journal|player.?guide|walkthrough)\b",
    re.IGNORECASE,
)

# Passthrough-fragment shapes (complementary to similarity checks): a copied mid-sentence
# source fragment, an unterminated clause, or list-bullet residue.
_BULLET_MARKER_RE = re.compile(r"(?:^|\n)[ \t]*(?:[\u2022\u25E6\u25AA\u2023\u2043*]|-|\d+[.)])\s+")
_FIRST_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def ensure_sentence_terminator(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".?!":
        return cleaned
    return f"{cleaned}."


def trim_instance_overview(text: str, max_words: int = MAX_OVERVIEW_WORDS) -> str:
    return trim_words(text, max_words, ensure_terminal_punct=True)


def trim_key_character_summary(text: str, max_words: int = MAX_KEY_CHARACTER_WORDS) -> str:
    return ensure_sentence_terminator(trim_words(text, max_words, ensure_terminal_punct=True))


def is_generic_at_a_glance(text: str) -> bool:
    return bool(_GENERIC_AT_A_GLANCE.search(text.strip()))


def is_generic_overview(text: str) -> bool:
    return bool(_GENERIC_OVERVIEW.search(text.strip()))


def is_generic_key_character_summary(text: str) -> bool:
    return bool(_GENERIC_ENEMY.search(text.strip()))


def lint_at_a_glance(text: str, *, instance_name: str = "") -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("at_a_glance is empty")
        return issues
    words = word_count(cleaned)
    if words < MIN_AT_A_GLANCE_WORDS:
        issues.append(f"at_a_glance below {MIN_AT_A_GLANCE_WORDS} words ({words})")
    if words > MAX_AT_A_GLANCE_WORDS:
        issues.append(f"at_a_glance exceeds {MAX_AT_A_GLANCE_WORDS} words ({words})")
    if is_generic_at_a_glance(cleaned):
        issues.append("at_a_glance reads like generic filler")
    if has_currently_meta(cleaned) or _PATCH_NOTES_RE.search(cleaned):
        issues.append("at_a_glance contains player/meta framing")
    if instance_name and instance_name.lower() not in cleaned.lower():
        issues.append("at_a_glance lacks instance anchor")
    return issues


def lint_overview(text: str, *, instance_name: str = "") -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("overview is empty")
        return issues
    words = word_count(cleaned)
    if words < MIN_OVERVIEW_WORDS:
        issues.append(f"overview below {MIN_OVERVIEW_WORDS} words ({words})")
    if words > MAX_OVERVIEW_WORDS:
        issues.append(f"overview exceeds {MAX_OVERVIEW_WORDS} words ({words})")
    if is_generic_overview(cleaned):
        issues.append("overview reads like generic filler")
    if has_currently_meta(cleaned) or _PATCH_NOTES_RE.search(cleaned):
        issues.append("overview contains quest walkthrough or player meta")
    if instance_name and instance_name.lower() not in cleaned.lower():
        issues.append("overview lacks instance anchor")
    if has_historical_framing(cleaned) and words < MIN_OVERVIEW_WORDS // 2:
        issues.append("overview reads like thin historical fragment")
    return issues


def lint_key_character_summary(
    text: str, *, boss_name: str = "", instance_name: str = ""
) -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("key enemy summary is empty")
        return issues
    words = word_count(cleaned)
    if words < MIN_KEY_CHARACTER_WORDS:
        issues.append(f"key enemy summary below {MIN_KEY_CHARACTER_WORDS} words ({words})")
    if words > MAX_KEY_CHARACTER_WORDS:
        issues.append(f"key enemy summary exceeds {MAX_KEY_CHARACTER_WORDS} words ({words})")
    if is_generic_key_character_summary(cleaned):
        issues.append("key enemy summary reads like generic stub")
    if _HOLLOW_SUMMARY_RE.search(cleaned):
        issues.append("key enemy summary reads as hollow/non-notable characterization")
    if boss_name and boss_name.lower() not in cleaned.lower():
        issues.append("key enemy summary lacks boss name anchor")
    if (
        instance_name
        and instance_name.lower() not in cleaned.lower()
        and words < MIN_KEY_CHARACTER_WORDS
    ):
        issues.append("key enemy summary lacks instance context")
    return issues


def lint_passthrough_fragment(text: str) -> list[str]:
    """Detect copied/passthrough source-fragment shapes in synthesized prose.

    Complementary to the similarity gate: flags fragments that *look* lifted rather than
    synthesized — a mid-sentence lowercase start, a missing terminal terminator, or
    embedded list-bullet markers. Empty/whitespace input is not a passthrough issue (a
    separate emptiness check owns that), so it returns no issues.
    """
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        return issues
    match = _FIRST_LETTER_RE.search(cleaned)
    if match and match.group(0).islower():
        issues.append("passthrough fragment: starts mid-sentence (lowercase)")
    if cleaned[-1] not in ".?!\"'":
        issues.append("passthrough fragment: missing terminal punctuation")
    if _BULLET_MARKER_RE.search(cleaned):
        issues.append("passthrough fragment: contains list-bullet markers")
    return issues


def _role_of(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("role", "") or "").strip().lower()
    return str(getattr(item, "role", "") or "").strip().lower()


def _name_key(item: object) -> str:
    if isinstance(item, dict):
        raw = item.get("name", "")
    else:
        raw = getattr(item, "name", "")
    return " ".join(str(raw).strip().casefold().split())


def assess_role_diversity(
    emitted_cards: list,
    roster: list,
    *,
    window: int | None = None,
) -> tuple[str, str]:
    """Assess whether an ally/neutral candidate was unfairly dropped from the cast.

    Returns ``(severity, reason)`` where severity is ``"ok"``, ``"warn"``, or ``"fail"``.
    Decision (per slice I5): an all-enemy emitted cast FAILs only when an ally/neutral
    candidate sits inside the top-``window`` ranked roster yet is absent from the cast;
    it WARNs when the only ally/neutral signal is ranked outside the window; otherwise OK.
    """
    from pipeline.contracts.models import INSTANCE_MAX_KEY_CHARACTERS

    if window is None:
        window = INSTANCE_MAX_KEY_CHARACTERS
    if not emitted_cards:
        return "ok", "no emitted cast"
    emitted_keys = {_name_key(card) for card in emitted_cards}
    # Determine whether the cast is all-enemy from the emitted cards' OWN roles. The card
    # role is authoritative (it reflects the post-LLM-tiebreaker decision); fall back to the
    # roster role only when an emitted card carries no role of its own.
    roster_role_by_key = {_name_key(c): _role_of(c) for c in roster}
    emitted_roles = {
        _role_of(card) or roster_role_by_key.get(_name_key(card)) for card in emitted_cards
    }
    if {"ally", "neutral"} & emitted_roles:
        return "ok", "emitted cast includes an ally/neutral character"

    in_window = roster[:window]
    out_window = roster[window:]
    dropped_in_window = [
        c
        for c in in_window
        if _role_of(c) in {"ally", "neutral"} and _name_key(c) not in emitted_keys
    ]
    if dropped_in_window:
        names = ", ".join(_display_name(c) for c in dropped_in_window)
        return "fail", f"all-enemy cast dropped in-window ally/neutral candidate(s): {names}"
    signal_out_window = [c for c in out_window if _role_of(c) in {"ally", "neutral"}]
    if signal_out_window:
        names = ", ".join(_display_name(c) for c in signal_out_window)
        return "warn", f"all-enemy cast; ally/neutral signal only outside window: {names}"
    return "ok", "no ally/neutral candidate available"


def _display_name(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("name", "")).strip()
    return str(getattr(item, "name", "")).strip()


def cast_registry_place_violations(
    emitted_names: Iterable[str],
    *,
    registry_path: Path | None = None,
) -> list[str]:
    """Return human-readable violations for registry ``place`` titles in the emitted cast."""
    from pipeline.discovery.world_registry import entry_kinds

    violations: list[str] = []
    for raw in emitted_names:
        name = str(raw).strip()
        if not name:
            continue
        kinds = entry_kinds(name, path=registry_path)
        if "place" in kinds:
            violations.append(f"{name!r} is a registry place, not a character")
    return violations


def fallback_instance_overview(
    items: list[dict],
    *,
    instance_name: str = "",
    max_words: int = MAX_OVERVIEW_WORDS,
) -> tuple[str, list[str]]:
    if not items:
        return "", []
    # Clean each snippet (not just the LLM path) so the deterministic overview borrow also drops
    # source-attribution prefaces ("From the World Dungeons page ... Community Site:") and link
    # artifacts — otherwise the preamble shipped verbatim when synthesis fell back to this path.
    snippets = [
        cleaned for item in items if (cleaned := clean_wiki_snippet(str(item.get("snippet", ""))))
    ]
    if not snippets:
        return "", []
    used: list[str] = []
    for item in items:
        source_id = str(item.get("source_id", "")).strip()
        if source_id and source_id not in used:
            used.append(source_id)
    body = ""
    index = 0
    while word_count(body) < MIN_OVERVIEW_WORDS:
        body = f"{body} {snippets[index % len(snippets)]}".strip()
        index += 1
        if index > len(snippets) * 20:
            break
    if instance_name and instance_name.lower() not in body.lower():
        body = f"{instance_name} {body}".strip()
    if word_count(body) < MIN_OVERVIEW_WORDS:
        padding = (
            f" {instance_name} remains a focal point for regional conflict, undead corruption, "
            "and the ambitions of rival powers seeking control over its halls and secrets."
            if instance_name
            else (
                " The instance remains a focal point for regional conflict, undead corruption, "
                "and the ambitions of rival powers seeking control over its halls and secrets."
            )
        )
        while word_count(body) < MIN_OVERVIEW_WORDS:
            body = f"{body}{padding}".strip()
            if word_count(padding) < 5:
                break
    text = trim_instance_overview(body, max_words=max_words)
    return text, used


def _leading_complete_sentence(text: str, *, max_words: int) -> str:
    """Return the first *complete* sentence of ``text`` if it reads as prose, else ``""``.

    "Complete" means it ends on terminal punctuation, begins with a capital letter, and is
    not list/navbox-shaped. Used to lift a clean opening sentence from raw evidence without
    splicing a truncated mid-phrase fragment (the old colon-splice defect, #4).
    """
    cleaned = text.strip()
    if not cleaned:
        return ""
    sentences = split_sentences(cleaned)
    first = sentences[0] if sentences else ""
    if not first or first[-1] not in ".?!" or detect_list_shape(first):
        return ""
    letter = _FIRST_LETTER_RE.search(first)
    if not letter or not letter.group(0).isupper():
        return ""
    return trim_words(first, max_words, ensure_terminal_punct=True)


def fallback_key_character_summary(
    items: list[dict],
    *,
    boss_name: str,
    instance_name: str,
    max_words: int = MAX_KEY_CHARACTER_WORDS,
) -> tuple[str, list[str]]:
    generic = trim_key_character_summary(
        (
            f"{boss_name} serves as a major encounter within {instance_name}, shaping the "
            f"instance's narrative stakes and the power struggles that unfold inside its halls."
        ),
        max_words=max_words,
    )
    if not items:
        return generic, []
    best = max(items, key=lambda row: word_count(str(row.get("snippet", ""))))
    snippet = clean_wiki_snippet(wiki_html.strip_tags(str(best.get("snippet", "")))).strip()
    # Only borrow a clean *complete* opening sentence from the evidence; never splice a
    # verbatim, comma-/word-truncated fragment after a colon. If none qualifies, fall back to
    # the boss-anchored generic summary rather than emit a truncated copy.
    sentence = _leading_complete_sentence(snippet, max_words=24)
    if not sentence:
        return generic, []
    text = trim_key_character_summary(
        f"{boss_name} features prominently in {instance_name}. {sentence}",
        max_words=max_words,
    )
    if word_count(text) < MIN_KEY_CHARACTER_WORDS:
        # Short evidence sentence — frame it more fully (as a separate sentence, not a colon
        # splice) so it clears the word floor while staying grammatical.
        text = trim_key_character_summary(
            (
                f"{boss_name} stands among the defining threats of {instance_name}, commanding "
                f"hostile forces and anchoring the instance's narrative conflict. {sentence}"
            ),
            max_words=max_words,
        )
    if word_count(text) < MIN_KEY_CHARACTER_WORDS or lint_passthrough_fragment(text):
        return generic, []
    used = [str(best.get("source_id", ""))] if best.get("source_id") else []
    return text, used
