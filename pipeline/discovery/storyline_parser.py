"""Parse Warcraft Wiki storyline pages into ordered quest graph nodes."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from pipeline.common.text_ids import slugify
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.discovery.entity_typing import is_valid_quest_graph_link


def _wiki_title(link: str) -> str:
    if "://" in link:
        path = urlparse(link).path
    else:
        path = link
    title = path.split("/wiki/", 1)[-1].split("#", 1)[0]
    return unquote(title).strip().replace("_", " ")


def _to_entity_id(prefix: str, title: str) -> str:
    slug = slugify(title)
    return f"{prefix}-{slug}" if slug else prefix


def _is_part_header(text: str) -> bool:
    return bool(re.match(r"(?i)^(part|chapter)\s+[0-9ivx]+", text.strip()))


def _is_quest_link(link: str, *, zone_name: str = "") -> bool:
    valid, _reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
    return valid


def _faction_from_section(section_role: str, heading_text: str) -> str:
    blob = f"{section_role} {heading_text}".lower()
    if "alliance" in blob:
        return "alliance"
    if "horde" in blob:
        return "horde"
    return "shared"


def parse_storyline_snapshot(
    snapshot: dict[str, Any],
    *,
    zone_id: str,
    cluster_key: str,
    zone_name: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (quest_graph_v1_rows, quest_graph_v2_rows) from a storyline snapshot."""
    section_blocks = snapshot.get("section_blocks", [])
    if not isinstance(section_blocks, list):
        section_blocks = []
    structured_links = snapshot.get("structured_links", [])
    wiki_links = snapshot.get("wiki_links", [])
    link_hrefs: list[str] = []
    if isinstance(structured_links, list):
        for row in structured_links:
            if isinstance(row, dict) and row.get("href"):
                link_hrefs.append(str(row["href"]))
    if isinstance(wiki_links, list):
        link_hrefs.extend(str(link) for link in wiki_links if isinstance(link, str))
    deduped_links = list(dict.fromkeys(link_hrefs))

    v1_rows: list[dict[str, Any]] = []
    v2_rows: list[dict[str, Any]] = []
    order = 0
    current_faction = "shared"
    current_section = "lead"

    for block in section_blocks:
        if not isinstance(block, dict):
            continue
        raw_section = str(block.get("section_role", "lead"))
        text = clean_wiki_snippet(str(block.get("text", "")))
        if not text:
            continue
        current_section = raw_section
        if _is_part_header(text):
            order += 1
            node_id = _to_entity_id("quest-part", text)
            prev_id = v2_rows[-1]["node_id"] if v2_rows else None
            if v2_rows:
                v2_rows[-1]["next_node_id"] = node_id
            v2_rows.append(
                {
                    "zone_id": zone_id,
                    "node_id": node_id,
                    "title": text,
                    "node_type": "part_header",
                    "order": order,
                    "prev_node_id": prev_id,
                    "next_node_id": None,
                    "cluster_key": cluster_key,
                    "faction_binding": current_faction,
                }
            )
            continue
        current_faction = _faction_from_section(current_section, text)

    quest_links = [link for link in deduped_links if _is_quest_link(link, zone_name=zone_name)]
    for link in quest_links:
        title = _wiki_title(link)
        if not title:
            continue
        order += 1
        quest_id = _to_entity_id("quest", title)
        prev_id = v2_rows[-1]["node_id"] if v2_rows else None
        if v2_rows:
            v2_rows[-1]["next_node_id"] = quest_id
        v2_rows.append(
            {
                "zone_id": zone_id,
                "node_id": quest_id,
                "title": title,
                "node_type": "quest",
                "order": order,
                "prev_node_id": prev_id,
                "next_node_id": None,
                "cluster_key": cluster_key,
                "faction_binding": current_faction,
                "source_link": link,
            }
        )
        v1_rows.append(
            {
                "zone_id": zone_id,
                "quest_node_id": quest_id,
                "title": title,
                "source_link": link,
                "faction_binding": current_faction,
                "location_binding": zone_id,
                "source_section_role": "quests_or_storyline",
            }
        )

    if not v2_rows and section_blocks:
        for block in section_blocks:
            if not isinstance(block, dict):
                continue
            text = clean_wiki_snippet(str(block.get("text", "")))
            if len(text.split()) < 4 or text.lower().startswith("see "):
                continue
            order += 1
            node_id = _to_entity_id("quest-step", text[:80])
            prev_id = v2_rows[-1]["node_id"] if v2_rows else None
            if v2_rows:
                v2_rows[-1]["next_node_id"] = node_id
            v2_rows.append(
                {
                    "zone_id": zone_id,
                    "node_id": node_id,
                    "title": text[:120],
                    "node_type": "questline_step",
                    "order": order,
                    "prev_node_id": prev_id,
                    "next_node_id": None,
                    "cluster_key": cluster_key,
                    "faction_binding": "shared",
                }
            )

    return v1_rows, v2_rows
