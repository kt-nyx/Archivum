"""Shared heuristics for zone prose quality (draft + semantic checks)."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.linguistics import tense_profile
from pipeline.common.text_sim import token_jaccard
from pipeline.contracts.models import ZONE_PAGE_BUDGET_RULES
from pipeline.discovery.world_registry import entry_kinds

_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
# Derives from the contracts BudgetRule registry (Slice 2), the same home validate's
# zone_page at_a_glance check reads. There is deliberately no lint word *floor* here:
# validate's minimum (18) is WARN-severity, and the <12-words filler heuristic in
# ``lint_at_a_glance`` is a degenerate-stub guard for the offline borrow ladder, not a budget.
MAX_AT_A_GLANCE_WORDS = ZONE_PAGE_BUDGET_RULES["at_a_glance"].max_words
MIN_HISTORY_SECTIONS = 3
MAX_HISTORY_SECTIONS = 8
AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD = 0.55
_SHORT_TEXT_PRESENT_CARVEOUT_WORDS = 8

_CURRENTLY_META_RE = re.compile(
    r"\breputation with\b|\bachievement\b|\bplayers can\b|\bbreadcrumb\b",
    re.IGNORECASE,
)
_ADP_DATE_RE = re.compile(r"\b(?:year\s+)?\d{1,3}\s+(?:A|B)DP\b", re.IGNORECASE)

_LOCATION_LIST_RE = re.compile(
    r"(?:[A-Z][a-z]+(?:'s)?(?:,\s*)?){3,}[A-Z][a-z]+",
)

# Player-facing quest-directive voice. `currently` / `at_a_glance` describe the world in-universe,
# not what the player is sent to do, yet quest-objective evidence ("Adventurers are tasked with...",
# "Aid the Argent Crusade...", "See <zone> storyline") otherwise slips into the currently pool and
# wins on length. This regex covers the *voice/address* half of the signal (second person,
# player-as-tasked-agent, or a wiki cross-reference directive); the bare-imperative half
# ("Aid...", "Slay...") comes from the grammar substrate's imperative shape in
# `has_player_directive`, not an enumerated verb list.
_PLAYER_DIRECTIVE_RE = re.compile(
    r"\b(?:you|your|yourself)\b"
    r"|\b(?:adventurers?|heroes?|champions?|players?)\s+"
    r"(?:are\s+(?:tasked|sent|asked|called|charged|dispatched)|must|should|can\s+(?:help|aid|assist))\b"
    r"|\bsee\b[^.]*\bstoryline\b",
    re.IGNORECASE,
)
# Fourth-wall / game-meta reference to the person at the keyboard. The compendium is in-world lore,
# so "the player", "the player's arrival", or second-person address ("you", "your") break the frame
# even inside otherwise-narrative prose — e.g. a present-state bridge that reads "By the player's
# arrival, the region is still...". Distinct from _PLAYER_DIRECTIVE_RE (quest-objective voice): this
# catches the bare meta noun regardless of directive phrasing. "player(s)" is never in-world; heroes,
# champions, and adventurers are canonical actors and are intentionally NOT matched here.
_PLAYER_META_RE = re.compile(
    r"\bplayers?\b|\byou\b|\byour\b|\byourself\b",
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


# Tense home (Slice 5): every tense/voice judgment below delegates to the NLP grammar
# substrate (pipeline.common.linguistics.tense_profile). The hand-enumerated past/present
# verb regexes are gone; past participles and adjectival participles ("ruined",
# "plague-scarred", "fallen") never count as finite past narration.


def has_dominant_present_tense(text: str) -> bool:
    """True when the finite present spine outweighs the finite past spine."""
    profile = tense_profile(text)
    return profile.present_count > profile.past_count


def past_marker_score(text: str) -> int:
    profile = tense_profile(text)
    return profile.past_count * 2 - profile.present_count


def has_past_tense_signal(text: str) -> bool:
    """Positive past evidence: a finite past verb spine or past/adjectival participles.

    Used for history-section framing, where participial scarring ("the ruined countryside")
    legitimately carries the past even in a sentence without a finite past verb.
    """
    profile = tense_profile(text)
    return profile.past_count > 0 or bool(profile.past_participles)


def is_past_dominant_narration(text: str) -> bool:
    """True when the text's only finite narration is past, and there is enough of it to be a spine.

    This is the deterministic "reads as history, not a present-state description" floor: at least
    two finite past verbs/auxiliaries and no finite present at all. The >=2 floor is deliberate —
    the pinned sm model can erase a lone present verb through a noun mis-tag ("control", "labors"),
    and a single subordinate past fact inside an otherwise nominal/present summary is legitimate
    supporting detail (the gold Forsaken card shape). Gates built on this reject on positive past
    evidence; they never require positive present evidence.
    """
    profile = tense_profile(text)
    return profile.present_count == 0 and profile.past_count >= 2


def has_currently_meta(text: str) -> bool:
    return bool(_CURRENTLY_META_RE.search(text))


# Category detector for the self-negating non-answer (RC6): a "summary" whose sentence asserts the
# ABSENCE of evidenced content ("no zone-specific role is evidenced", "their motive is not stated")
# instead of stating content. Detected as negation + an epistemic/evidence verb in the same
# sentence — the category, not an enumeration of phrasings.
_NON_ANSWER_NEGATION_RE = re.compile(r"\b(no|not|none|nothing|never|without|neither)\b", re.IGNORECASE)
_NON_ANSWER_EPISTEMIC_RE = re.compile(
    r"\b(evidence[ds]?|stated|specified|mentioned|described|documented|attested|recorded|"
    r"indicated|confirmed|established|noted|detailed|provided|available|given)\b",
    re.IGNORECASE,
)


def is_self_negating_non_answer(text: str) -> bool:
    """True when any sentence asserts the absence of content rather than content.

    A synthesis result in this category is a non-answer regardless of phrasing; callers route it
    to the synthesis driver's retry → explicit failure, never publish it as a summary.
    """
    for sentence in split_sentences(text):
        if _NON_ANSWER_NEGATION_RE.search(sentence) and _NON_ANSWER_EPISTEMIC_RE.search(sentence):
            return True
    return False


def has_player_directive(text: str) -> bool:
    """True when the text reads as a player-facing quest directive rather than in-universe prose.

    Two signals: the explicit player/meta frame regex (second person, player-as-tasked-agent,
    wiki cross-reference directive — mechanical frame guards), and the grammar substrate's
    imperative shape (a subjectless base-form clause head: "Slay the necromancers", "Be warned"),
    which replaces the old enumerated quest-verb opener list.
    """
    cleaned = text.strip()
    if not cleaned:
        return False
    if _PLAYER_DIRECTIVE_RE.search(cleaned):
        return True
    return tense_profile(cleaned).imperative_like


def has_player_meta_reference(text: str) -> bool:
    """True when the prose breaks the in-world frame with a game-meta reference to the player.

    Catches the bare noun ("the player", "the player's arrival") and second-person address, which
    :func:`has_player_directive` misses because they carry no quest-objective verb.
    """
    return bool(_PLAYER_META_RE.search(text))


def has_present_state_framing(text: str) -> bool:
    """True when the text carries a finite present verb or present copula/auxiliary spine."""
    return tense_profile(text).present_framed


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
    # at_a_glance is an essence caption: it describes what the zone IS, carrying its history through
    # scarring/legacy *adjectives* ("plague-scarred", "fallen", "ruined") rather than narrating past
    # events. Reject a caption whose verb spine is dominantly past tense (it reads as a history blurb);
    # a present/atemporal or nominal caption — including the all-participle gold shape — is fine. This
    # gates on finite past-tense verbs only, so past-participle adjectives never trip it.
    if words >= _SHORT_TEXT_PRESENT_CARVEOUT_WORDS and tense_profile(text).past_dominant:
        issues.append(
            "at_a_glance reads as past-tense narration: describe what the zone is now, "
            "carrying its history in adjectives rather than past-tense events"
        )
    if is_self_negating_non_answer(text):
        issues.append("at_a_glance asserts absence of content instead of describing the subject")
    issues.extend(lint_adp_date_style(text))
    return issues


def lint_currently(text: str, *, zone_name: str = "", at_a_glance: str = "") -> list[str]:
    issues: list[str] = []
    # Reject an actual location *list dump*, not any landmark mention: present-state lore legitimately
    # names where the recovery and conflict are happening ("the Argent Crusade still holds Hearthglen;
    # Caer Darrow remains a school of necromancy"). The stricter geography-hub check rejected that as a
    # "geography hub" and dropped the zone's real present-state line to a canned fallback. Aligns with
    # lint_at_a_glance and the present-state-lore election tier, which both gate on list dumps only.
    if has_location_list_dump(text):
        issues.append("currently reads like a location list dump")
    if has_currently_meta(text):
        issues.append("currently contains reputation/achievement/player meta")
    if has_player_directive(text):
        issues.append("currently reads as a player-facing quest directive")
    if has_player_meta_reference(text):
        issues.append("currently references the player / breaks in-world frame")
    if at_a_glance.strip():
        overlap = token_jaccard(at_a_glance, text)
        if overlap >= AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD:
            issues.append("currently substantially overlaps at_a_glance")
    words = word_count(text)
    if words >= _SHORT_TEXT_PRESENT_CARVEOUT_WORDS and not has_present_state_framing(text):
        issues.append(
            "currently lacks present-tense active-state framing: describe the zone's "
            "ongoing state in present tense"
        )
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
    final_index = len(sections) - 1
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        body = str(section.get("body", "")).strip()
        if not body:
            issues.append(f"history_sections[{index}] has empty body")
            continue
        # In-world frame guard — applies to every section, including the present-state bridge, which
        # is otherwise exempt from the tense checks below and is the section most tempted to write
        # "by the player's arrival" as its present-day anchor.
        if has_player_meta_reference(body):
            issues.append(f"history_sections[{index}] references the player / breaks in-world frame")
        # The final section of a multi-section history is the present-state bridge: the chronicle
        # catching up to the zone's current, ongoing condition. It may be written in present tense,
        # so it is exempt from the past-tense framing / dominant-present checks. Every earlier section
        # stays hard-guarded past, so background eras can never be present-tensed; a lone section is
        # never exempt (a one-section "history" must still read as past background).
        is_present_state_bridge = index == final_index and len(sections) > 1
        if not is_present_state_bridge:
            if has_dominant_present_tense(body):
                issues.append(
                    f"history_sections[{index}] uses dominant present tense: "
                    "narrate this era's completed events in past tense"
                )
            elif not has_past_tense_signal(body):
                issues.append(
                    f"history_sections[{index}] lacks past-tense historical framing: "
                    "narrate the era's events in past tense"
                )
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
