"""Shared wiki evidence filters for discovery enrich and draft prose election."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.discovery_vocab import non_canon_body_markers
from pipeline.common.section_registry import (
    is_bare_history_container,
    section_content_class,
)

# WS-C: body-text non-canon markers externalized to
# pipeline/data/discovery_classification_vocab.v1.json (D-6).
_NON_CANON_MARKERS = non_canon_body_markers()

_RPG_DISCLAIMER_RE = re.compile(
    r"this section contains information from the warcraft rpg",
    re.IGNORECASE,
)

_EXPANSION_BOILERPLATE_RE = re.compile(
    r"^this section concerns content related to",
    re.IGNORECASE,
)

_SIMILE_CONTINENT_RE_TEMPLATE = r"\b(?:as|like|just as|similar to)\s+(?:in|to)\s+{continent}\b"


def is_rpg_section(raw_section_role: str) -> bool:
    # Non-canon sections (Warcraft RPG) are the section registry's non_canon class; centralize the
    # definition there rather than repeating the ``in_the_rpg`` prefix test.
    return section_content_class(raw_section_role) == "non_canon"


def is_non_canon_history_snippet(text: str) -> bool:
    lowered = str(text).strip().lower()
    if not lowered:
        return False
    if any(marker in lowered for marker in _NON_CANON_MARKERS):
        return True
    return bool(_RPG_DISCLAIMER_RE.search(lowered))


def is_expansion_boilerplate(text: str) -> bool:
    return bool(_EXPANSION_BOILERPLATE_RE.search(str(text).strip()))


def is_named_history_section(raw_section_role: str, parent_section_role: str = "") -> bool:
    """True for a distinctive narrative history subsection ("The Scourging", "Cataclysm") worth
    reserving as its own section — i.e. registry-narrative (with the canonical/parent role supplying
    inheritance for unlisted subsection slugs) and not a bare container heading (History/Lead/…).
    RPG, geography, gameplay, meta and media sections are all non-narrative and therefore excluded.
    """
    if not str(raw_section_role).strip():
        return False
    if section_content_class(raw_section_role, parent_section_role) != "narrative":
        return False
    return not is_bare_history_container(raw_section_role)


def evidence_item_content_class(item: dict[str, Any]) -> str:
    """Registry content_class for a draft evidence item.

    Uses the item's canonical ``section_role`` as the inherited-parent fallback for its raw slug, so
    a distinctive subsection ("Scourging of Lordaeron") inherits ``narrative`` from its History
    parent while an adaptation section ("Exploring Azeroth") keeps its own ``media`` class.
    """
    raw = str(item.get("raw_section_role", item.get("section_role", ""))).strip()
    canonical = str(item.get("section_role", "")).strip()
    return section_content_class(raw, canonical)


def is_simile_continent_mention(snippet: str, continent_title: str) -> bool:
    title = str(continent_title).strip()
    if not title:
        return False
    pattern = _SIMILE_CONTINENT_RE_TEMPLATE.format(continent=re.escape(title))
    return bool(re.search(pattern, snippet, re.IGNORECASE))


def should_exclude_from_history(item: dict[str, Any]) -> bool:
    raw_section = str(item.get("raw_section_role", item.get("section_role", ""))).strip()
    if is_rpg_section(raw_section):
        return True
    snippet = str(item.get("snippet", "")).strip()
    if not snippet:
        return True
    if is_non_canon_history_snippet(snippet):
        return True
    return is_expansion_boilerplate(snippet)


def _item_block_index(item: dict[str, Any]) -> int:
    value = item.get("block_index")
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _item_source_id(item: dict[str, Any]) -> str:
    return str(item.get("source_id", ""))


def _item_raw_section(item: dict[str, Any]) -> str:
    return str(item.get("raw_section_role", item.get("section_role", ""))).strip().lower()


def _item_canonical_section(item: dict[str, Any]) -> str:
    return str(item.get("section_role", "")).strip().lower()


def group_items_by_raw_section(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = sorted(items, key=lambda row: (_item_block_index(row), _item_source_id(row)))
    groups: list[list[dict[str, Any]]] = []
    current_role: str | None = None
    current_group: list[dict[str, Any]] = []
    for item in ordered:
        role = _item_raw_section(item)
        if role != current_role:
            if current_group:
                groups.append(current_group)
            current_group = [item]
            current_role = role
        else:
            current_group.append(item)
    if current_group:
        groups.append(current_group)
    return groups


def trailing_named_section_items(
    items: list[dict[str, Any]],
    *,
    max_groups: int = 2,
) -> list[dict[str, Any]]:
    named_groups = [
        group
        for group in group_items_by_raw_section(items)
        if group
        and is_named_history_section(
            _item_raw_section(group[0]), _item_canonical_section(group[0])
        )
    ]
    if not named_groups:
        return []
    trailing = named_groups[-max_groups:]
    return [item for group in trailing for item in group]


def cap_history_pool(items: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    if cap <= 0 or not items:
        return []
    if len(items) <= cap:
        return list(items)

    ordered = sorted(items, key=lambda row: (_item_block_index(row), _item_source_id(row)))
    trailing = trailing_named_section_items(ordered, max_groups=2)
    trailing_ids = {id(item) for item in trailing}

    reserved = [item for item in ordered if id(item) in trailing_ids]
    if len(reserved) > cap:
        reserved = reserved[-cap:]
        trailing_ids = {id(item) for item in reserved}

    budget = cap - len(reserved)
    picked: list[dict[str, Any]] = []
    for item in ordered:
        if id(item) in trailing_ids:
            continue
        picked.append(item)
        if len(picked) >= budget:
            break

    merged_ids = {id(item) for item in picked + reserved}
    return [item for item in ordered if id(item) in merged_ids]
