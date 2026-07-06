"""Resolve questline card start anchors from QuestRecord chain heads (Slice D)."""

from __future__ import annotations

from typing import Any

from pipeline.common.discovery_vocab import entry_quest_title_keywords
from pipeline.discovery.questline_cluster import normalize_quest_title, resolve_title_to_node_id

# WS-C: externalized to pipeline/data/discovery_classification_vocab.v1.json (D-6).
# Chain heads are computed structurally (indegree 0); this list only PREFERS the
# breadcrumb head by title. Game-wide breadcrumb conventions only (Slice 11 evicted
# the zone-specific titles); curated registry arcs carry their own start_anchor.
ENTRY_QUEST_TITLE_KEYWORDS = entry_quest_title_keywords()


def _record_faction(record: dict[str, Any], roster_row: dict[str, Any]) -> str:
    faction = str(record.get("faction", "")).strip().lower()
    if faction in {"alliance", "horde"}:
        return faction
    binding = str(roster_row.get("faction_binding", "shared")).strip().lower()
    if binding in {"alliance", "horde", "shared"}:
        return binding
    return "shared"


def _quest_title(record: dict[str, Any], roster_row: dict[str, Any]) -> str:
    return str(record.get("quest_title", "") or roster_row.get("title", "")).strip()


def _title_matches_entry_keyword(title: str) -> bool:
    normalized = normalize_quest_title(title)
    return any(keyword in normalized for keyword in ENTRY_QUEST_TITLE_KEYWORDS)


def _build_title_index(
    member_node_ids: list[str],
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for node_id in member_node_ids:
        roster = roster_by_node.get(node_id, {})
        record = records_by_node.get(node_id, {})
        for title in {_quest_title(record, roster), str(roster.get("title", "")).strip()}:
            key = normalize_quest_title(title)
            if key and node_id not in index.get(key, []):
                index.setdefault(key, []).append(node_id)
    return index


def chain_head_node_ids(
    member_node_ids: list[str],
    *,
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
) -> list[str]:
    """Return node_ids with no in-cluster previous quest edge."""
    member_set = set(member_node_ids)
    title_index = _build_title_index(member_node_ids, records_by_node, roster_by_node)
    indegree: dict[str, int] = {node_id: 0 for node_id in member_node_ids}
    for node_id in member_node_ids:
        record = records_by_node.get(node_id, {})
        roster = roster_by_node.get(node_id, {})
        if not record.get("has_questbox", True):
            continue
        faction = _record_faction(record, roster)
        for prev_title in record.get("previous", []):
            prev_id = resolve_title_to_node_id(
                str(prev_title),
                title_index=title_index,
                prefer_faction=faction,
                records_by_node=records_by_node,
                roster_by_node=roster_by_node,
            )
            if prev_id and prev_id in member_set:
                indegree[node_id] = indegree.get(node_id, 0) + 1
    return [node_id for node_id in member_node_ids if indegree.get(node_id, 0) == 0]


def resolve_cluster_start_anchor(
    *,
    cluster_id: str,
    ordered_quest_rows: list[dict[str, Any]],
    records_by_node: dict[str, dict[str, Any]],
) -> str:
    """Pick the player-facing breadcrumb quest title for a cluster card."""
    _ = cluster_id
    roster_by_node = {
        str(row.get("node_id", "")): row
        for row in ordered_quest_rows
        if str(row.get("node_id", "")).strip()
    }
    member_node_ids = sorted(
        roster_by_node,
        key=lambda node_id: int(roster_by_node[node_id].get("order_in_cluster", 0) or 0),
    )
    if not member_node_ids:
        return "Questline"

    heads = chain_head_node_ids(
        member_node_ids,
        records_by_node=records_by_node,
        roster_by_node=roster_by_node,
    )
    entry_heads = [
        node_id
        for node_id in heads
        if _title_matches_entry_keyword(
            _quest_title(records_by_node.get(node_id, {}), roster_by_node[node_id])
        )
    ]
    chosen = sorted(
        entry_heads or heads or member_node_ids,
        key=lambda node_id: int(roster_by_node[node_id].get("order_in_cluster", 0) or 0),
    )[0]
    record = records_by_node.get(chosen, {})
    roster = roster_by_node.get(chosen, {})
    title = _quest_title(record, roster)
    return title or str(roster.get("title", "Questline"))
