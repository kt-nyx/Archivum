"""Loader for the externalized discovery classification vocabulary (WS-C / D-6).

The classification keyword lists that survive the D-6 gate (no structural
category/infobox/section signal at the pre-fetch link-decision point, no viable
statistical signal for a short title) live in
``pipeline/data/discovery_classification_vocab.v1.json`` rather than inline in
code. This module reads them once and exposes them as immutable tuples so call
sites keep the same shape they had as module-level constants.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pipeline.common.io import read_json

_VOCAB_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "discovery_classification_vocab.v1.json"
)


@lru_cache(maxsize=1)
def _vocab() -> dict[str, object]:
    blob = read_json(_VOCAB_PATH)
    if not isinstance(blob, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"discovery vocab must be a JSON object: {_VOCAB_PATH}")
    return blob


def _tokens(key: str) -> tuple[str, ...]:
    entry = _vocab().get(key)
    if not isinstance(entry, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"discovery vocab missing entry: {key}")
    tokens = entry.get("tokens")
    if not isinstance(tokens, list):  # pragma: no cover - corrupt data file
        raise RuntimeError(f"discovery vocab entry {key!r} missing 'tokens' list")
    return tuple(str(token) for token in tokens)


def _frozenset(key: str) -> frozenset[str]:
    return frozenset(_tokens(key))


def faction_title_tokens() -> tuple[str, ...]:
    return _tokens("faction_title_tokens")


def event_title_tokens() -> tuple[str, ...]:
    return _tokens("event_title_tokens")


def character_role_hints() -> tuple[str, ...]:
    return _tokens("character_role_hints")


def non_location_title_tokens() -> tuple[str, ...]:
    return _tokens("non_location_title_tokens")


def location_hard_reject_tokens() -> tuple[str, ...]:
    return _tokens("location_hard_reject_tokens")


def location_rpg_tokens() -> tuple[str, ...]:
    return _tokens("location_rpg_tokens")


def location_type_title_rules() -> tuple[tuple[str, frozenset[str]], ...]:
    """Ordered (location_type, name-token set) rules for sub-location typing.

    First matching category wins, so callers must preserve list order. See the
    ``location_type_title_tokens`` entry in the vocab JSON for ordering rationale.
    """
    entry = _vocab().get("location_type_title_tokens")
    if not isinstance(entry, dict):  # pragma: no cover - corrupt data file
        raise RuntimeError("discovery vocab missing entry: location_type_title_tokens")
    rules = entry.get("ordered_rules")
    if not isinstance(rules, list):  # pragma: no cover - corrupt data file
        raise RuntimeError("location_type_title_tokens missing 'ordered_rules' list")
    out: list[tuple[str, frozenset[str]]] = []
    for rule in rules:
        if not isinstance(rule, dict):  # pragma: no cover - corrupt data file
            raise RuntimeError("location_type_title_tokens rule must be an object")
        location_type = str(rule["location_type"])
        tokens = frozenset(str(token) for token in rule.get("tokens", []))
        out.append((location_type, tokens))
    return tuple(out)


def lore_faction_tokens() -> tuple[str, ...]:
    return _tokens("lore_faction_tokens")


def lore_character_role_hints() -> tuple[str, ...]:
    return _tokens("lore_character_role_hints")


def race_species_denylist() -> frozenset[str]:
    return _frozenset("entity_typing_race_species_denylist")


def meta_page_denylist() -> frozenset[str]:
    return _frozenset("entity_typing_meta_page_denylist")


def location_meta_titles() -> frozenset[str]:
    return _frozenset("entity_typing_location_meta_titles")


def faction_as_location_denylist() -> frozenset[str]:
    return _frozenset("entity_typing_faction_as_location_denylist")


def quest_alliance_binding_tokens() -> tuple[str, ...]:
    return _tokens("quest_alliance_binding_tokens")


def quest_horde_binding_tokens() -> tuple[str, ...]:
    return _tokens("quest_horde_binding_tokens")


def entry_quest_title_keywords() -> frozenset[str]:
    return _frozenset("entry_quest_title_keywords")


def non_canon_body_markers() -> tuple[str, ...]:
    return _tokens("non_canon_body_markers")


def generic_non_person_words() -> frozenset[str]:
    return _frozenset("generic_non_person_words")


def boss_reject_section_titles() -> frozenset[str]:
    return _frozenset("boss_reject_section_titles")


def non_character_titles() -> frozenset[str]:
    return _frozenset("non_character_titles")


def non_person_narrative_titles() -> frozenset[str]:
    return _frozenset("non_person_narrative_titles")
