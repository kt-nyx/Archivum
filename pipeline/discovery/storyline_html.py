"""Parse Warcraft Wiki storyline page HTML into quest graph v3 rows."""

from __future__ import annotations

import re
from typing import Any, Iterator

from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.storyline_parser import _to_entity_id, _wiki_title

_HEADING_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TABLE_HEADING_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.IGNORECASE | re.DOTALL)
_BOLD_HEADING_RE = re.compile(r"<b[^>]*>(.*?)</b>", re.IGNORECASE | re.DOTALL)
_THUMB_CAPTION_RE = re.compile(
    r'<div[^>]*class="[^"]*thumbcaption[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_LEVEL_RE = re.compile(r"\[[0-9]+(?:-[0-9]+)?\]")
_LIST_ITEM_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_QUEST_ROW_RE = re.compile(
    r'<span[^>]*class="[^"]*questlong-prefix[^"]*"[^>]*>(.*?)</span>\s*'
    r'<a\s+[^>]*href="(/wiki/[^"#]+)"',
    re.IGNORECASE | re.DOTALL,
)
_ICON_FACTION = (
    ("alliance", "alliance_15"),
    ("horde", "horde_15"),
    ("neutral", "neutral_15"),
    ("shared", "both_15"),
)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "cluster-main"


def _clean_text(raw: str) -> str:
    return " ".join(_TAG_RE.sub(" ", raw).split()).strip()


def _collect_headings(html: str) -> list[tuple[int, str, str, int]]:
    """Return (offset, slug, title, heading_level) sorted by document order."""
    events: list[tuple[int, str, str, int]] = []
    for match in _HEADING_RE.finditer(html):
        title = _clean_text(match.group(2))
        if title:
            events.append((match.start(), _slugify(title), title, int(match.group(1))))
    for match in _TABLE_HEADING_RE.finditer(html):
        title = _clean_text(match.group(1))
        if title and len(title.split()) >= 2:
            events.append((match.start(), _slugify(title), title, 4))
    for match in _THUMB_CAPTION_RE.finditer(html):
        title = _clean_text(match.group(1))
        if title and len(title.split()) >= 2:
            events.append((match.start(), _slugify(title), title, 5))
    for match in _BOLD_HEADING_RE.finditer(html):
        title = _clean_text(match.group(1))
        if title and 2 <= len(title.split()) <= 8 and title[0].isupper():
            events.append((match.start(), _slugify(title), title, 6))
    events.sort(key=lambda row: row[0])
    deduped: list[tuple[int, str, str, int]] = []
    seen_slugs: set[str] = set()
    for event in events:
        if event[1] in seen_slugs:
            continue
        seen_slugs.add(event[1])
        deduped.append(event)
    return deduped


def _faction_from_icon_chunk(icon_chunk: str, anchor_chunk: str = "") -> str:
    lowered = f"{icon_chunk} {anchor_chunk}".lower()
    for binding, token in _ICON_FACTION:
        if token in lowered:
            return binding
    return "shared"


def _level_range_from_chunk(html_chunk: str) -> str | None:
    match = _LEVEL_RE.search(_TAG_RE.sub(" ", html_chunk))
    if not match:
        return None
    return match.group(0).strip()


def _iter_list_item_quest_matches(html: str) -> Iterator[tuple[int, re.Match[str]]]:
    """Yield quest row matches that appear inside storyline list items only."""
    for list_item in _LIST_ITEM_RE.finditer(html):
        item_html = list_item.group(1)
        item_offset = list_item.start(1)
        for quest_match in _QUEST_ROW_RE.finditer(item_html):
            yield item_offset + quest_match.start(), quest_match


def parse_storyline_html(
    html: str,
    *,
    zone_id: str,
    zone_name: str = "",
) -> list[dict[str, Any]]:
    """Return v3 quest graph rows from storyline page HTML."""
    if not html.strip():
        return []

    rows: list[dict[str, Any]] = []
    default_cluster_id = "cluster-main"
    default_cluster_title = "Main storylines"
    cluster_order_counters: dict[str, int] = {}
    seen_hrefs: set[str] = set()

    headings = _collect_headings(html)

    def cluster_for_offset(offset: int) -> tuple[str, str, int, int]:
        if not headings:
            return default_cluster_id, default_cluster_title, 1, 2
        active = headings[0]
        for heading in headings:
            if heading[0] <= offset:
                active = heading
            else:
                break
        slug, title, heading_level = active[1], active[2], active[3]
        order = next((index + 1 for index, item in enumerate(headings) if item[1] == slug), 1)
        return slug, title, order, heading_level

    for absolute_offset, quest_match in _iter_list_item_quest_matches(html):
        icon_chunk = quest_match.group(1)
        href = quest_match.group(2)
        normalized_href = href.split("#", 1)[0]
        if normalized_href in seen_hrefs:
            continue
        valid, _reasons = is_valid_quest_graph_link(normalized_href, zone_name=zone_name)
        if not valid:
            continue
        title = _wiki_title(normalized_href)
        if not title:
            continue
        seen_hrefs.add(normalized_href)
        cid, ctitle, corder, heading_level = cluster_for_offset(absolute_offset)
        cluster_order_counters[cid] = cluster_order_counters.get(cid, 0) + 1
        order_in_cluster = cluster_order_counters[cid]
        block = quest_match.group(0)
        rows.append(
            {
                "zone_id": zone_id,
                "cluster_id": cid,
                "cluster_title": ctitle,
                "cluster_order": corder,
                "heading_level": heading_level,
                "node_id": _to_entity_id("quest", title),
                "title": title,
                "node_type": "quest",
                "faction_binding": _faction_from_icon_chunk(icon_chunk, block),
                "level_range": _level_range_from_chunk(block),
                "order_in_cluster": order_in_cluster,
                "source_link": normalized_href,
            }
        )

    return rows


def v3_to_legacy_v1(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project v3 quest nodes to legacy v1 quest graph shape."""
    legacy: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("node_type", "")) != "quest":
            continue
        legacy.append(
            {
                "zone_id": str(row.get("zone_id", "")),
                "quest_node_id": str(row.get("node_id", "")),
                "title": str(row.get("title", "")),
                "source_link": str(row.get("source_link", "")),
                "faction_binding": str(row.get("faction_binding", "shared")),
                "location_binding": str(row.get("zone_id", "")),
                "source_section_role": "quests_or_storyline",
            }
        )
    return legacy
