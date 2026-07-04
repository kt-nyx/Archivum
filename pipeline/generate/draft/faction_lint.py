"""Shared heuristics for major_factions card quality (draft + semantic checks)."""

from __future__ import annotations

import re

from pipeline.generate.draft.prose_lint import (
    has_currently_meta,
    has_historical_framing,
    is_self_negating_non_answer,
    lint_adp_date_style,
    split_sentences,
    trim_words,
    word_count,
)

MIN_FACTION_SUMMARY_WORDS = 12
MAX_FACTION_SUMMARY_WORDS = 40


def strip_faction_label_prefix(text: str, faction_name: str = "") -> str:
    """Remove an internal ``"<Faction>: "`` binding label from summary text.

    Role-pool evidence snippets are stored as ``"<Faction>: <snippet>"`` to bind a structured link
    to its context (see faction_scoring); that label is an internal artifact and must never surface
    in a published summary (the "Scourge: The Scholomance…" defect when the deterministic fallback
    borrows such a snippet verbatim).
    """
    cleaned = text.strip()
    name = faction_name.strip()
    if name and cleaned.lower().startswith(f"{name.lower()}:"):
        return cleaned[len(name) + 1 :].lstrip()
    return cleaned

# One remaining vacuous-identity pattern. The old canned-template phrasings ("appears in this
# zone's active conflicts", "political narrative") were removed as redundant: they carry no
# present-role predicate, so the positive substance gate (role framing + subject mention + zone
# anchor + non-answer detection) already rejects them.
_GENERIC_FILLER_PATTERNS = (
    re.compile(r"\bis a .+ faction\b", re.IGNORECASE),
)

_PRESENT_ROLE_RE = re.compile(
    r"\b("
    r"is|are|remains|remain|continues|continue|holds|hold|operates|operate|controls|control|"
    r"maintains|maintain|coordinates|coordinate|patrols|patrol|guards|guard|"
    r"pushes|push|sends|send|defends|defend|occupies|occupy|uses|use|serves|serve|"
    r"trains|train|raises|raise"
    r")\b",
    re.IGNORECASE,
)


def ensure_sentence_terminator(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".?!":
        return cleaned
    return f"{cleaned}."


def _clause_trim(sentence: str, max_words: int) -> str:
    """Trim a single over-long sentence at a comma/semicolon boundary, not mid-phrase.

    A borrowed wiki lede is often one long clause chain that overflows the cap; a bare word-cap cut
    severs a proper noun ("…city of Caer." for "Caer Darrow"). Keeping whole clauses cuts at the
    last clause that fits instead.
    """
    clauses = [clause.strip() for clause in re.split(r"[;,]", sentence) if clause.strip()]
    kept: list[str] = []
    running = 0
    for clause in clauses:
        clause_words = word_count(clause)
        if kept and running + clause_words > max_words:
            break
        kept.append(clause)
        running += clause_words
        if running >= max_words:
            break
    joined = ", ".join(kept)
    # Even the first clause can overflow; fall back to a bounded hard trim so the result stays capped.
    return joined if word_count(joined) <= max_words else trim_words(sentence, max_words)


def trim_faction_summary(text: str, max_words: int = MAX_FACTION_SUMMARY_WORDS) -> str:
    cleaned = text.strip()
    if word_count(cleaned) <= max_words:
        return ensure_sentence_terminator(cleaned)
    kept: list[str] = []
    running = 0
    for sentence in split_sentences(cleaned):
        sentence_words = word_count(sentence)
        if running + sentence_words > max_words:
            if not kept:
                # The leading sentence alone overflows: clause-trim it rather than sever a phrase.
                kept.append(_clause_trim(sentence, max_words))
            break
        kept.append(sentence)
        running += sentence_words
    return ensure_sentence_terminator(" ".join(kept).strip())


def is_generic_faction_summary(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    return any(pattern.search(cleaned) for pattern in _GENERIC_FILLER_PATTERNS)


def has_zone_role_framing(text: str) -> bool:
    return bool(_PRESENT_ROLE_RE.search(text)) or has_historical_framing(text)


def summary_has_zone_anchor(text: str, *, zone_name: str, subregion_tokens: list[str]) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if zone_name and zone_name.lower() in cleaned.lower():
        return True
    for token in subregion_tokens:
        if token and token.lower() in cleaned.lower():
            return True
    return False


_SUBJECT_MENTION_STOPWORDS = frozenset({"of", "the", "and", "a", "an"})


def summary_mentions_subject(text: str, faction_name: str) -> bool:
    """True when the summary names the subject faction (full name or a significant name token).

    Positive substance gate (RC6): a faction card must describe *this* faction, not merely recount
    facts about entities found near it. A significant token suffices ("the cult" for "Cult of the
    Damned") so natural pronoun-style shorthand still passes.
    """
    cleaned = text.strip().lower()
    name = faction_name.strip().lower()
    if not cleaned or not name:
        return True  # nothing to check against; other lints handle empties
    if name in cleaned:
        return True
    words = set(re.findall(r"[\w']+", cleaned))
    return any(
        token in words
        for token in re.findall(r"[\w']+", name)
        if len(token) > 2 and token not in _SUBJECT_MENTION_STOPWORDS
    )


def lint_faction_summary(
    text: str,
    *,
    zone_name: str = "",
    subregion_tokens: list[str] | None = None,
    faction_name: str = "",
) -> list[str]:
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        issues.append("faction summary is empty")
        return issues
    words = word_count(cleaned)
    if words < MIN_FACTION_SUMMARY_WORDS:
        issues.append(f"faction summary below {MIN_FACTION_SUMMARY_WORDS} words ({words})")
    if words > MAX_FACTION_SUMMARY_WORDS:
        issues.append(f"faction summary exceeds {MAX_FACTION_SUMMARY_WORDS} words ({words})")
    if cleaned[-1] not in ".?!":
        issues.append("faction summary does not end with sentence punctuation")
    if is_generic_faction_summary(cleaned):
        issues.append("faction summary reads like generic filler")
    if has_currently_meta(cleaned):
        issues.append("faction summary contains reputation/achievement/player meta")
    if is_self_negating_non_answer(cleaned):
        issues.append("faction summary asserts absence of content instead of a role (non-answer)")
    if faction_name and not summary_mentions_subject(cleaned, faction_name):
        issues.append("faction summary never names the faction it describes")
    if zone_name and zone_name.lower() in cleaned.lower() and words < MIN_FACTION_SUMMARY_WORDS:
        issues.append("faction summary reads like bare zone-description filler")
    if words >= MIN_FACTION_SUMMARY_WORDS and not has_zone_role_framing(cleaned):
        issues.append("faction summary lacks zone role framing")
    issues.extend(lint_adp_date_style(cleaned))
    tokens = subregion_tokens or []
    if (
        zone_name
        and words >= MIN_FACTION_SUMMARY_WORDS
        and not summary_has_zone_anchor(
            cleaned,
            zone_name=zone_name,
            subregion_tokens=tokens,
        )
    ):
        issues.append("faction summary lacks zone or subregion anchor")
    return issues
