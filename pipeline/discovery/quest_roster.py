"""Build a flat, unclustered quest roster for a zone.

The roster is the complete list of quest pages to traverse, decoupled from any
clustering. The primary source is the zone's storyline article links; when those
are missing or too thin (e.g. zones with no/stub storyline page), we fall back to
the ``Category:<Zone> quests`` membership via the shared throttled MediaWiki
helper. Questbox confirmation is deferred to traverse time, so this stage only
applies cheap title-level filtering.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.storyline_html import parse_storyline_html
from pipeline.discovery.storyline_parser import _to_entity_id
from pipeline.discovery.world_registry import _fetch_category_members as fetch_category_members

_UNCLUSTERED_ID = "unclustered"
_UNCLUSTERED_TITLE = "Unclustered"


def _flat_row(
    *,
    zone_id: str,
    title: str,
    source_link: str,
    faction_binding: str,
    level_range: str | None,
    order: int,
) -> dict[str, Any]:
    return {
        "zone_id": zone_id,
        "cluster_id": _UNCLUSTERED_ID,
        "cluster_title": _UNCLUSTERED_TITLE,
        "cluster_order": 1,
        "heading_level": 2,
        "node_id": _to_entity_id("quest", title),
        "title": title,
        "node_type": "quest",
        "faction_binding": faction_binding or "shared",
        "level_range": level_range,
        "order_in_cluster": order,
        "source_link": source_link,
    }


def _normalized_link(link: str) -> str:
    return link.strip().lower().split("#", 1)[0]


def _category_title(zone_name: str) -> str:
    return f"Category:{zone_name} quests"


def build_quest_roster(
    *,
    zone_id: str,
    zone_name: str,
    storyline_html: str,
    min_storyline_quests: int = 3,
    fetch_members: Callable[..., list[dict[str, Any]]] = fetch_category_members,
    sleep_seconds: float = 0.35,
) -> list[dict[str, Any]]:
    """Return flat (``cluster_id="unclustered"``) quest roster rows for a zone."""
    roster: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    def _add(title: str, source_link: str, faction_binding: str, level_range: str | None) -> None:
        link_key = _normalized_link(source_link)
        if not title or not link_key or link_key in seen_links:
            return
        seen_links.add(link_key)
        roster.append(
            _flat_row(
                zone_id=zone_id,
                title=title,
                source_link=source_link,
                faction_binding=faction_binding,
                level_range=level_range,
                order=len(roster) + 1,
            )
        )

    for row in parse_storyline_html(storyline_html, zone_id=zone_id, zone_name=zone_name):
        if str(row.get("node_type", "")) != "quest":
            continue
        _add(
            str(row.get("title", "")),
            str(row.get("source_link", "")),
            str(row.get("faction_binding", "shared")),
            row.get("level_range"),
        )

    if len(roster) >= min_storyline_quests or not zone_name:
        return roster

    members = fetch_members(
        _category_title(zone_name),
        cmtype="page",
        sleep_seconds=sleep_seconds,
    )
    for member in members:
        if not isinstance(member, dict):
            continue
        if int(member.get("ns", 0)) != 0:
            continue
        title = str(member.get("title", "")).strip()
        if not title:
            continue
        link = f"/wiki/{title.replace(' ', '_')}"
        valid, _reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
        if not valid:
            continue
        _add(title, link, "shared", None)

    return roster


def category_quest_links(
    zone_name: str,
    *,
    fetch_members: Callable[..., list[dict[str, Any]]] = fetch_category_members,
    sleep_seconds: float = 0.35,
) -> list[str]:
    """Return ``/wiki/...`` quest links from ``Category:<Zone> quests`` (filtered)."""
    if not zone_name:
        return []
    links: list[str] = []
    seen: set[str] = set()
    members = fetch_members(_category_title(zone_name), cmtype="page", sleep_seconds=sleep_seconds)
    for member in members:
        if not isinstance(member, dict) or int(member.get("ns", 0)) != 0:
            continue
        title = str(member.get("title", "")).strip()
        if not title:
            continue
        link = f"/wiki/{title.replace(' ', '_')}"
        valid, _reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
        key = _normalized_link(link)
        if not valid or key in seen:
            continue
        seen.add(key)
        links.append(link)
    return links


__all__ = ["build_quest_roster", "category_quest_links"]
