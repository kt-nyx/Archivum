"""Parse Warcraft Wiki storyline page HTML into quest graph v3 rows."""

from __future__ import annotations

import re
from typing import Any

from bs4.element import Tag

from pipeline.common import wiki_html
from pipeline.common.text_ids import slugify
from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.storyline_parser import _to_entity_id, _wiki_title

_LEVEL_RE = re.compile(r"\[[0-9]+(?:-[0-9]+)?\]")
_ICON_FACTION = (
    ("alliance", "alliance_15"),
    ("horde", "horde_15"),
    ("neutral", "neutral_15"),
    ("shared", "both_15"),
)


def _slugify(text: str) -> str:
    return slugify(text) or "cluster-main"


def _clean(element: Tag) -> str:
    return " ".join(element.get_text(" ").split()).strip()


def _has_class(element: Tag, token: str) -> bool:
    return token in (element.get("class") or [])


def _heading_candidate(element: Tag) -> tuple[str, str, int] | None:
    """Return (slug, title, heading_level) when an element qualifies as a cluster heading."""
    name = element.name.lower()
    if name in {"h2", "h3"}:
        title = _clean(element)
        return (_slugify(title), title, int(name[1])) if title else None
    if name == "th":
        title = _clean(element)
        return (_slugify(title), title, 4) if title and len(title.split()) >= 2 else None
    if name == "div" and _has_class(element, "thumbcaption"):
        title = _clean(element)
        return (_slugify(title), title, 5) if title and len(title.split()) >= 2 else None
    if name == "b":
        title = _clean(element)
        if title and 2 <= len(title.split()) <= 8 and title[0].isupper():
            return (_slugify(title), title, 6)
        return None
    return None


def _faction_from_icon_chunk(icon_chunk: str, anchor_chunk: str = "") -> str:
    lowered = f"{icon_chunk} {anchor_chunk}".lower()
    for binding, token in _ICON_FACTION:
        if token in lowered:
            return binding
    return "shared"


def _level_range_from_chunk(html_chunk: str) -> str | None:
    match = _LEVEL_RE.search(wiki_html.strip_tags(html_chunk))
    if not match:
        return None
    return match.group(0).strip()


def _following_quest_anchor(span: Tag) -> Tag | None:
    """Return the anchor that immediately follows ``span`` (whitespace only between)."""
    for sibling in span.next_siblings:
        if isinstance(sibling, Tag):
            if sibling.name.lower() == "a" and str(sibling.get("href", "")).startswith("/wiki/"):
                return sibling
            return None
        if str(sibling).strip():
            return None
    return None


def collect_heading_events(html: str) -> list[tuple[int, str, str, int]]:
    """Return deduped cluster headings as ``(doc_index, slug, title, heading_level)``.

    Document-order index replaces the previous character offset; it is stable across calls
    on the same HTML, so it can be compared against :func:`anchor_index_map` values.
    """
    headings: list[tuple[int, str, str, int]] = []
    seen_slugs: set[str] = set()
    for index, element in enumerate(wiki_html.soup(html).descendants):
        if not isinstance(element, Tag):
            continue
        candidate = _heading_candidate(element)
        if candidate is not None and candidate[0] not in seen_slugs:
            seen_slugs.add(candidate[0])
            headings.append((index, candidate[0], candidate[1], candidate[2]))
    return headings


def anchor_index_map(html: str) -> dict[str, int]:
    """Map ``/wiki/...`` href (without fragment) to its first document-order index."""
    out: dict[str, int] = {}
    for index, element in enumerate(wiki_html.soup(html).descendants):
        if isinstance(element, Tag) and element.name.lower() == "a":
            href = str(element.get("href", "")).split("#", 1)[0]
            if href and href not in out:
                out[href] = index
    return out


def parse_storyline_html(
    html: str,
    *,
    zone_id: str,
    zone_name: str = "",
) -> list[dict[str, Any]]:
    """Return v3 quest graph rows from storyline page HTML."""
    if not html.strip():
        return []

    default_cluster_id = "cluster-main"
    default_cluster_title = "Main storylines"

    # Deduped headings + quest rows (questlong-prefix span + following anchor, inside a list
    # item), tagged with monotonic document-order indices so cluster assignment matches the
    # old character-offset walk.
    headings = collect_heading_events(html)
    quest_events: list[tuple[int, Tag, Tag]] = []
    for index, element in enumerate(wiki_html.soup(html).descendants):
        if (
            isinstance(element, Tag)
            and element.name.lower() == "span"
            and _has_class(element, "questlong-prefix")
            and element.find_parent("li") is not None
        ):
            anchor = _following_quest_anchor(element)
            if anchor is not None:
                quest_events.append((index, element, anchor))

    def cluster_for_index(index: int) -> tuple[str, str, int, int]:
        if not headings:
            return default_cluster_id, default_cluster_title, 1, 2
        active = headings[0]
        for heading in headings:
            if heading[0] <= index:
                active = heading
            else:
                break
        slug, title, heading_level = active[1], active[2], active[3]
        order = next((i + 1 for i, item in enumerate(headings) if item[1] == slug), 1)
        return slug, title, order, heading_level

    rows: list[dict[str, Any]] = []
    cluster_order_counters: dict[str, int] = {}
    seen_hrefs: set[str] = set()
    for index, span, anchor in quest_events:
        href = str(anchor.get("href", ""))
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
        cid, ctitle, corder, heading_level = cluster_for_index(index)
        cluster_order_counters[cid] = cluster_order_counters.get(cid, 0) + 1
        chunk = str(span)
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
                "faction_binding": _faction_from_icon_chunk(chunk, str(anchor)),
                "level_range": _level_range_from_chunk(chunk),
                "order_in_cluster": cluster_order_counters[cid],
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
