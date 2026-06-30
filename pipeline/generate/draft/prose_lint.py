"""Shared heuristics for zone prose quality (draft + semantic checks)."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.draft_vocab import historical_framing_markers
from pipeline.common.text_sim import token_jaccard
from pipeline.discovery.world_registry import entry_kinds

_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
MAX_AT_A_GLANCE_WORDS = 45
MIN_HISTORY_SECTIONS = 3
MAX_HISTORY_SECTIONS = 8
AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD = 0.55
_SHORT_TEXT_PRESENT_CARVEOUT_WORDS = 8

# WS-C: prose-text historical-framing markers externalized to
# pipeline/data/draft_classification_vocab.v1.json (D-6).
_HISTORICAL_MARKERS = historical_framing_markers()

_CURRENTLY_META_RE = re.compile(
    r"\breputation with\b|\bachievement\b|\bplayers can\b|\bbreadcrumb\b",
    re.IGNORECASE,
)
_ADP_DATE_RE = re.compile(r"\b(?:year\s+)?\d{1,3}\s+(?:A|B)DP\b", re.IGNORECASE)

_PAST_TENSE_RE = re.compile(
    r"\b(was|were|had been|became|fell|destroyed|invaded|established|founded|consumed|overran|collapsed|remained)\b",
    re.IGNORECASE,
)

# Generic English past-tense/participle morphology (regular -ed / -en endings on a word stem).
# Used only for history-section *framing* detection — a domain-general grammar signal, not a lore
# vocabulary list — so legitimate past-tense narration (razed, marched, perished, abandoned, …) is
# recognized without enumerating zone verbs. Present-dominant sections that happen to contain an
# -ed adjective are still caught by `has_dominant_present_tense` (the framing check's `elif` branch).
_PAST_TENSE_MORPH_RE = re.compile(r"\b[a-z]{2,}(?:ed|en)\b", re.IGNORECASE)

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

# Player-facing quest-directive voice. `currently` / `at_a_glance` describe the world in-universe,
# not what the player is sent to do, yet quest-objective evidence ("Adventurers are tasked with...",
# "Aid the Argent Crusade...", "See <zone> storyline") otherwise slips into the currently pool and
# wins on length. This is a *voice/address* signal (second person, player-as-tasked-agent, bare
# imperative opener, or a wiki cross-reference directive) — general English quest phrasing, not a
# zone vocabulary list — so it generalizes across zones without hardcoding any one zone's content.
_PLAYER_DIRECTIVE_RE = re.compile(
    r"\b(?:you|your|yourself)\b"
    r"|\b(?:adventurers?|heroes?|champions?|players?)\s+"
    r"(?:are\s+(?:tasked|sent|asked|called|charged|dispatched)|must|should|can\s+(?:help|aid|assist))\b"
    r"|\bsee\b[^.]*\bstoryline\b",
    re.IGNORECASE,
)
_QUEST_IMPERATIVE_OPENER_RE = re.compile(
    r"^\s*(?:aid|help|assist|defeat|slay|kill|destroy|stop|halt|find|seek|locate|travel|journey|"
    r"venture|head|go|return|report|speak|talk|meet|escort|rescue|free|gather|collect|retrieve|"
    r"deliver|bring|clear|defend|protect|investigate|search|beware|be\s+warned)\b",
    re.IGNORECASE,
)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")


def split_sentences(text: str) -> list[str]:
    """Split on sentence-terminal punctuation, returning stripped, non-empty sentences.

    Single source of truth for the ``(?<=[.?!])\\s+`` split used by the CTA finalizer and the
    key-character sentence-borrow fallback (formerly a duplicated regex in each).
    """
    return [chunk.strip() for chunk in _SENTENCE_SPLIT_RE.split(text) if chunk.strip()]


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def has_adp_date(text: str) -> bool:
    return bool(_ADP_DATE_RE.search(text))


def lint_adp_date_style(text: str) -> list[str]:
    if has_adp_date(text):
        return ["prose uses exact ADP/BDP dating instead of era/event framing"]
    return []


def _hard_trim_words(text: str, max_words: int) -> str:
    """Whitespace word-cap trim with a regex-count backstop (no sentence awareness)."""
    words = text.split()
    result = " ".join(words[:max_words]).strip() if len(words) > max_words else text.strip()
    # `word_count` (regex) splits on punctuation/dashes, so it can count *more* words than
    # the whitespace split above ("necromancy—located" is one split token but two regex
    # words). The linters enforce the regex count, so trim further until that count is in
    # budget — otherwise a one-word overshoot rejects the field and ships it empty.
    trimmed = result.split()
    while trimmed and word_count(result) > max_words:
        trimmed = trimmed[:-1]
        result = " ".join(trimmed).strip()
    return result


def trim_words(text: str, max_words: int, *, ensure_terminal_punct: bool = False) -> str:
    """Trim ``text`` to ``max_words``, preferring whole-sentence boundaries.

    Over-budget text keeps the longest leading run of *complete* sentences that fits the cap,
    so a hard cut never severs the final sentence mid-phrase (the "...Caer Darrow secretly."
    defect). Falls back to a hard word-cap trim only when even the first sentence overflows the
    cap (a single long run-on, or punctuation-free text), so the result is always bounded and
    never dropped to empty.
    """
    cleaned = text.strip()
    if word_count(cleaned) <= max_words:
        result = cleaned
    else:
        kept: list[str] = []
        running = 0
        for sentence in split_sentences(cleaned):
            sentence_words = word_count(sentence)
            if running + sentence_words > max_words and (kept or sentence_words > max_words):
                break
            kept.append(sentence)
            running += sentence_words
        # A kept run always ends on a sentence terminator (the split point), so it satisfies
        # `ensure_terminal_punct` without an appended period. The hard-trim fallback may not.
        result = " ".join(kept).strip() if kept else _hard_trim_words(cleaned, max_words)
    if ensure_terminal_punct and result and result[-1] not in ".?!":
        return f"{result}."
    return result


def tense_marker_counts(text: str) -> tuple[int, int]:
    past = len(_PAST_TENSE_RE.findall(text))
    present = len(_PRESENT_TENSE_RE.findall(text))
    return past, present


def has_dominant_present_tense(
    text: str, *, short_text_word_limit: int = _SHORT_TEXT_PRESENT_CARVEOUT_WORDS
) -> bool:
    past, present = tense_marker_counts(text)
    if present == 0:
        return False
    if past == 0 and word_count(text) < short_text_word_limit:
        return False
    return present > past or (present >= 1 and past == 0)


def past_marker_score(text: str) -> int:
    past, present = tense_marker_counts(text)
    return past * 2 - present


def has_past_tense_signal(text: str) -> bool:
    """Generic past-tense signal: a common irregular past verb or regular -ed/-en morphology.

    Domain-general grammar rule (no lore/proper-noun tokens) used for history-section framing, so a
    legitimate past-tense section is not rejected merely for avoiding the small irregular-verb list.
    """
    return bool(_PAST_TENSE_RE.search(text)) or bool(_PAST_TENSE_MORPH_RE.search(text))


def has_historical_framing(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _HISTORICAL_MARKERS)


def has_currently_meta(text: str) -> bool:
    return bool(_CURRENTLY_META_RE.search(text))


def has_player_directive(text: str) -> bool:
    """True when the text reads as a player-facing quest directive rather than in-universe prose."""
    cleaned = text.strip()
    if not cleaned:
        return False
    return bool(_PLAYER_DIRECTIVE_RE.search(cleaned) or _QUEST_IMPERATIVE_OPENER_RE.search(cleaned))


def has_present_state_framing(text: str) -> bool:
    """True when the text carries present-tense active-state framing (is/remains/holds/...)."""
    return bool(_PRESENT_TENSE_RE.search(text))


def has_geography_hub_in_text(text: str) -> bool:
    for token in re.findall(r"[A-Z][a-z]+(?:[''][a-z]+)?(?:\s+[A-Z][a-z]+)*", text):
        if entry_kinds(token.strip()) & _GEOGRAPHY_KINDS:
            return True
    return False


def has_location_list_dump(text: str) -> bool:
    if _LOCATION_LIST_RE.search(text):
        return True
    geography_hits = sum(
        1 for token in re.findall(r"\b[A-Z][a-z]+\b", text) if entry_kinds(token) & _GEOGRAPHY_KINDS
    )
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
    issues.extend(lint_adp_date_style(text))
    return issues


def lint_currently(text: str, *, zone_name: str = "", at_a_glance: str = "") -> list[str]:
    issues: list[str] = []
    if has_geography_hub_in_text(text):
        issues.append("currently mentions geography hub proper nouns")
    if has_currently_meta(text):
        issues.append("currently contains reputation/achievement/player meta")
    if has_player_directive(text):
        issues.append("currently reads as a player-facing quest directive")
    if at_a_glance.strip():
        overlap = token_jaccard(at_a_glance, text)
        if overlap >= AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD:
            issues.append("currently substantially overlaps at_a_glance")
    words = word_count(text)
    if words >= _SHORT_TEXT_PRESENT_CARVEOUT_WORDS and not _PRESENT_TENSE_RE.search(text):
        issues.append("currently lacks present-tense active-state framing")
    elif has_historical_framing(text) and not _PRESENT_TENSE_RE.search(text):
        issues.append("currently uses historical-era framing without present tense")
    issues.extend(lint_adp_date_style(text))
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
        has_framing = has_past_tense_signal(body) or has_historical_framing(body)
        if not has_framing:
            issues.append(f"history_sections[{index}] lacks past-tense historical framing")
        elif has_dominant_present_tense(body, short_text_word_limit=0):
            issues.append(f"history_sections[{index}] uses dominant present tense")
        for adp_issue in lint_adp_date_style(body):
            issues.append(f"history_sections[{index}] {adp_issue}")
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
