"""Layered questline cluster transforms for v3 quest graph rows."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pipeline.common.text_ids import slugify
from pipeline.discovery.storyline_html import anchor_index_map, collect_heading_events

_GENERIC_CLUSTER_TITLES = frozenset({"main storylines", "main storyline", ""})
_MAX_CLUSTER_QUESTS = 15


def _slugify(text: str) -> str:
    return slugify(text) or "cluster-main"


def _is_generic_cluster_title(title: str) -> bool:
    return title.strip().lower() in _GENERIC_CLUSTER_TITLES


def infer_hub_titles(rows: list[dict[str, Any]], html: str) -> list[dict[str, Any]]:
    if not rows:
        return rows
    headings = collect_heading_events(html)
    if not headings:
        return rows
    anchor_offsets = anchor_index_map(html)
    updated: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("node_type", "")) != "quest":
            updated.append(dict(row))
            continue
        out = dict(row)
        title = str(out.get("cluster_title", ""))
        if not _is_generic_cluster_title(title):
            updated.append(out)
            continue
        source_link = str(out.get("source_link", ""))
        offset = anchor_offsets.get(source_link.split("#", 1)[0], -1) if source_link else -1
        if offset < 0:
            updated.append(out)
            continue
        active = headings[0]
        for heading in headings:
            if heading[0] <= offset:
                active = heading
            else:
                break
        out["cluster_id"] = active[1]
        out["cluster_title"] = active[2]
        out["cluster_order"] = next((index + 1 for index, item in enumerate(headings) if item[1] == active[1]), 1)
        out["heading_level"] = active[3]
        updated.append(out)
    return updated


def _cluster_groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("node_type", "")) != "quest":
            continue
        zone_id = str(row.get("zone_id", ""))
        cluster_id = str(row.get("cluster_id", "cluster-main"))
        groups[(zone_id, cluster_id)].append(dict(row))
    for key in groups:
        groups[key].sort(key=lambda row: int(row.get("order_in_cluster", 0) or 0))
    return groups


def _faction_suffix(binding: str) -> str:
    if binding == "alliance":
        return "alliance"
    if binding == "horde":
        return "horde"
    return "shared"


def split_by_faction(rows: list[dict[str, Any]], *, max_quests: int = _MAX_CLUSTER_QUESTS) -> list[dict[str, Any]]:
    groups = _cluster_groups(rows)
    output: list[dict[str, Any]] = []
    non_quest = [dict(row) for row in rows if str(row.get("node_type", "")) != "quest"]
    for (zone_id, cluster_id), quests in sorted(groups.items()):
        bindings = {str(row.get("faction_binding", "shared")) for row in quests}
        mixed_faction = len({b for b in bindings if b in {"alliance", "horde"}}) > 1
        needs_split = len(quests) > max_quests or (
            mixed_faction and len(quests) >= 4
        )
        if not needs_split:
            output.extend(quests)
            continue
        by_faction: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for quest in quests:
            binding = str(quest.get("faction_binding", "shared"))
            if binding in {"alliance", "horde"}:
                by_faction[binding].append(quest)
            else:
                by_faction["shared"].append(quest)
        for binding, faction_quests in sorted(by_faction.items()):
            if not faction_quests:
                continue
            suffix = _faction_suffix(binding)
            new_cluster_id = f"{cluster_id}-{suffix}"
            base_title = str(faction_quests[0].get("cluster_title", "Main storylines"))
            new_title = f"{base_title} ({suffix.title()})" if suffix != "shared" else base_title
            for index, quest in enumerate(faction_quests, start=1):
                updated = dict(quest)
                updated["cluster_id"] = new_cluster_id
                updated["cluster_title"] = new_title
                updated["order_in_cluster"] = index
                output.append(updated)
    output.extend(non_quest)
    output.sort(
        key=lambda row: (
            str(row.get("zone_id", "")),
            str(row.get("cluster_order", 0)),
            str(row.get("cluster_id", "")),
            int(row.get("order_in_cluster", 0) or 0),
        )
    )
    return output


def _level_band_slug(level_range: str | None) -> str:
    if not level_range:
        return "unknown-level"
    cleaned = level_range.strip("[]")
    return _slugify(cleaned.replace("-", "-to-"))


def split_by_level_band(rows: list[dict[str, Any]], *, max_quests: int = _MAX_CLUSTER_QUESTS) -> list[dict[str, Any]]:
    groups = _cluster_groups(rows)
    output: list[dict[str, Any]] = []
    non_quest = [dict(row) for row in rows if str(row.get("node_type", "")) != "quest"]
    for (_zone_id, cluster_id), quests in sorted(groups.items()):
        if len(quests) <= max_quests:
            output.extend(quests)
            continue
        by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for quest in quests:
            band = _level_band_slug(quest.get("level_range"))
            by_band[band].append(quest)
        if len(by_band) <= 1:
            output.extend(quests)
            continue
        for band, band_quests in sorted(by_band.items()):
            if not band_quests:
                continue
            new_cluster_id = f"{cluster_id}-{band}"
            base_title = str(band_quests[0].get("cluster_title", "Main storylines"))
            band_label = band.replace("-", " ").title()
            new_title = f"{base_title} [{band_label}]"
            for index, quest in enumerate(band_quests, start=1):
                updated = dict(quest)
                updated["cluster_id"] = new_cluster_id
                updated["cluster_title"] = new_title
                updated["order_in_cluster"] = index
                output.append(updated)
    output.extend(non_quest)
    output.sort(
        key=lambda row: (
            str(row.get("zone_id", "")),
            str(row.get("cluster_order", 0)),
            str(row.get("cluster_id", "")),
            int(row.get("order_in_cluster", 0) or 0),
        )
    )
    return output


def apply_cluster_layers(
    rows: list[dict[str, Any]],
    *,
    html: str = "",
) -> list[dict[str, Any]]:
    """Apply L4 hub titles, then L2 faction split, then L3 level-band split."""
    layered = infer_hub_titles(rows, html)
    layered = split_by_faction(layered)
    layered = split_by_level_band(layered)
    return layered
