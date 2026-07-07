"""Extract lore-bearing snippets from quest page section blocks."""

from __future__ import annotations

import re
from typing import Any

from pipeline.common.section_registry import section_content_class
from pipeline.common.text_normalize import clean_wiki_snippet

# Quest-page narrative sections: the in-game quest journal text (lede, description, objectives,
# quest text). The section registry classes these 'gameplay'/'meta' for zone/faction pages, but on a
# quest page they ARE the lore — so this page-type inclusion is explicit (Slice 14). The reward /
# progression / log / patch apparatus shares the "quest" token but is not narrative.
_QUEST_NARRATIVE_ROLE_TOKENS = (
    "description",
    "objective",
    "quest_text",
    "quest_detail",
    "quest",
    "overview",
    "summary",
)
_QUEST_APPARATUS_TOKENS = ("reward", "progression", "log", "patch")
_BOILERPLATE_RE = re.compile(
    r"(?:wowhead|wowpedia|database|db link|click here|patch \d+\.\d+|level \d+ quest)",
    re.IGNORECASE,
)
_MIN_SNIPPET_CHARS = 20


def _normalize_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


def _is_lore_section(section_role: str, parent_section_role: str = "") -> bool:
    """True for a quest section carrying narrative lore.

    Registry ``narrative`` sections always qualify (with parent inheritance); on top of that, the
    quest-journal sections (description / objectives / quest text) qualify by their page-type role
    even though the registry classes them gameplay/meta — excluding the reward/progression/log/patch
    apparatus that shares the "quest" token.
    """
    if section_content_class(section_role, parent_section_role) == "narrative":
        return True
    lowered = _normalize_role(section_role)
    if any(token in lowered for token in _QUEST_NARRATIVE_ROLE_TOKENS):
        return not any(bad in lowered for bad in _QUEST_APPARATUS_TOKENS)
    return False


def _is_boilerplate(text: str) -> bool:
    if _BOILERPLATE_RE.search(text):
        return True
    if text.count("|") >= 4 and text.count("\n") == 0:
        return True
    return False


def extract_quest_lore(section_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return narrative snippets suitable for quest lore evidence.

    Each snippet keeps its source block's inline article ``links`` (Slice 12
    required schema — empty list when the block has none).
    """
    snippets: list[dict[str, Any]] = []
    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        raw_role = str(block.get("section_role", "other"))
        parent_role = str(block.get("parent_section_role", ""))
        text = clean_wiki_snippet(str(block.get("text", "")))
        if len(text) < _MIN_SNIPPET_CHARS:
            continue
        if _is_boilerplate(text):
            continue
        if not _is_lore_section(raw_role, parent_role):
            continue
        raw_links = block.get("links")
        snippets.append(
            {
                "section_role": raw_role,
                "text": text,
                "links": raw_links if isinstance(raw_links, list) else [],
            }
        )
    return snippets


def lore_word_count(snippets: list[dict[str, Any]]) -> int:
    return sum(len(str(row.get("text", "")).split()) for row in snippets)


def build_quest_lore_record(
    *,
    zone_id: str,
    cluster_id: str,
    node_id: str,
    quest_title: str,
    source_link: str,
    section_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    snippets = extract_quest_lore(section_blocks)
    return {
        "zone_id": zone_id,
        "cluster_id": cluster_id,
        "node_id": node_id,
        "quest_title": quest_title,
        "source_link": source_link,
        "snippets": snippets,
        "lore_word_count": lore_word_count(snippets),
    }
