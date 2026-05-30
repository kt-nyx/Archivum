"""Zone-agnostic geography helpers for draft metadata."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.wiki_evidence_filters import is_simile_continent_mention

# In-game UI parent continents (valid parent_continent outputs).
IN_GAME_PARENT_CONTINENTS: tuple[str, ...] = (
    "Azeroth",
    "Eastern Kingdoms",
    "Kalimdor",
    "Northrend",
    "Pandaria",
    "Broken Isles",
    "Dragon Isles",
    "Zandalar",
    "Kul Tiras",
    "Outland",
    "Draenor",
    "Shadowlands",
    "K'aresh",
)

# Lore sub-regions map to an in-game parent; never emitted directly.
LORE_SUBREGION_TO_PARENT: dict[str, str] = {
    "Lordaeron": "Eastern Kingdoms",
    "Khaz Modan": "Eastern Kingdoms",
}

CONTINENT_TITLES: tuple[str, ...] = IN_GAME_PARENT_CONTINENTS + tuple(LORE_SUBREGION_TO_PARENT)

_FIELD_TIERS: tuple[str, ...] = (
    "geography_input",
    "at_a_glance_input",
    "currently_input",
    "history_digest",
)

_SEED_FIELD_NAMES = frozenset(_FIELD_TIERS)


def title_to_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower())
    return slug.strip("-")


def _is_seed_row(row: dict[str, Any]) -> bool:
    build_meta = row.get("build_meta") or {}
    source_kind = str(build_meta.get("source_kind", "")).strip()
    return not source_kind or source_kind == "seed"


def _snippets_for_field(
    evidence_rows: list[dict[str, Any]],
    field_name: str,
) -> list[str]:
    snippets: list[str] = []
    for row in evidence_rows:
        if str(row.get("field_name", "")) != field_name:
            continue
        if not _is_seed_row(row):
            continue
        for item in row.get("evidence_items") or []:
            if not isinstance(item, dict):
                continue
            snippet = str(item.get("snippet", "")).strip()
            if snippet:
                snippets.append(snippet)
    return snippets


def _match_in_game_parent(snippets: list[str]) -> str | None:
    for title in sorted(IN_GAME_PARENT_CONTINENTS, key=len, reverse=True):
        pattern = rf"\b{re.escape(title)}\b"
        for snippet in snippets:
            if is_simile_continent_mention(snippet, title):
                continue
            if re.search(pattern, snippet, re.IGNORECASE):
                return title_to_slug(title)
    return None


def _match_lore_subregion_parent(snippets: list[str]) -> str | None:
    for title in sorted(LORE_SUBREGION_TO_PARENT, key=len, reverse=True):
        pattern = rf"\b{re.escape(title)}\b"
        for snippet in snippets:
            if is_simile_continent_mention(snippet, title):
                continue
            if re.search(pattern, snippet, re.IGNORECASE):
                parent = LORE_SUBREGION_TO_PARENT[title]
                return title_to_slug(parent)
    return None


def resolve_parent_continent(evidence_rows: list[dict[str, Any]]) -> str | None:
    """Infer in-game parent continent slug from tiered seed evidence snippets."""
    for field_name in _FIELD_TIERS:
        snippets = _snippets_for_field(evidence_rows, field_name)
        if not snippets:
            continue
        parent = _match_in_game_parent(snippets)
        if parent:
            return parent
        parent = _match_lore_subregion_parent(snippets)
        if parent:
            return parent
    return None
