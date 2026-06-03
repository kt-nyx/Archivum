"""Post-traverse questline clustering from QuestRecord prev/next chains.

Slice B replaces heading-first partitioning with a prereq-graph approach:
chain-connected components, conservative org-bridged merges, faction splits,
and size guardrails. Storyline HTML headings may inform cluster titles only.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from pipeline.discovery.questline_clustering import (
    _MAX_CLUSTER_QUESTS,
    split_by_level_band,
)
from pipeline.discovery.storyline_html import _slugify

_ALGORITHM_VERSION = "v1-prereq-graph"
_ORPHAN_CLUSTER_ID = "orphan"
_LEVEL_PREFIX_RE = re.compile(r"^\[[0-9]+(?:-[0-9]+)?\]\s*")
_TITLE_KEYWORD_HINTS: tuple[tuple[str, str], ...] = (
    ("andorhal", "Battle for Andorhal"),
    ("mender", "Mender's Stead"),
    ("hearthglen", "Hearthglen"),
    ("tirion", "Hearthglen"),
    ("gahrron", "Gahrron's Withering"),
    ("northridge", "Northridge Lumber Mill"),
    ("cenarion", "Mender's Stead"),
)


def normalize_quest_title(title: str) -> str:
    """Normalize a quest title for prev/next resolution (strip level prefixes)."""
    cleaned = _LEVEL_PREFIX_RE.sub("", title.strip())
    cleaned = re.sub(r"[^\w\s'-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def _record_faction(record: dict[str, Any], roster_row: dict[str, Any]) -> str:
    faction = str(record.get("faction", "")).strip().lower()
    if faction in {"alliance", "horde"}:
        return faction
    binding = str(roster_row.get("faction_binding", "shared")).strip().lower()
    if binding in {"alliance", "horde", "shared"}:
        return binding
    return "shared"


def _build_title_index(
    roster_rows: list[dict[str, Any]],
    records_by_node: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for row in roster_rows:
        if str(row.get("node_type", "")) != "quest":
            continue
        node_id = str(row.get("node_id", "")).strip()
        if not node_id:
            continue
        titles = {str(row.get("title", "")).strip()}
        record = records_by_node.get(node_id, {})
        if record:
            titles.add(str(record.get("quest_title", "")).strip())
        for title in titles:
            key = normalize_quest_title(title)
            if key and node_id not in index[key]:
                index[key].append(node_id)
    return dict(index)


def resolve_title_to_node_id(
    title: str,
    *,
    title_index: dict[str, list[str]],
    prefer_faction: str,
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
) -> str | None:
    """Resolve a prev/next title string to a roster node_id."""
    key = normalize_quest_title(title)
    if not key:
        return None
    candidates = title_index.get(key, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if prefer_faction in {"alliance", "horde"}:
        for node_id in candidates:
            record = records_by_node.get(node_id, {})
            roster = roster_by_node.get(node_id, {})
            if _record_faction(record, roster) == prefer_faction:
                return node_id
    return candidates[0]


def build_chain_adjacency(
    *,
    node_ids: list[str],
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
    title_index: dict[str, list[str]],
) -> tuple[dict[str, set[str]], int]:
    """Return undirected adjacency from resolved prev/next edges and unresolved count."""
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    unresolved = 0
    for node_id in node_ids:
        record = records_by_node.get(node_id)
        roster = roster_by_node.get(node_id, {})
        if not record or not record.get("has_questbox", True):
            continue
        faction = _record_faction(record, roster)
        linked: set[str] = set()
        for edge_title in list(record.get("previous", [])) + list(record.get("next", [])):
            target = resolve_title_to_node_id(
                str(edge_title),
                title_index=title_index,
                prefer_faction=faction,
                records_by_node=records_by_node,
                roster_by_node=roster_by_node,
            )
            if target and target in adjacency:
                linked.add(target)
            elif str(edge_title).strip():
                unresolved += 1
        for target in linked:
            adjacency[node_id].add(target)
            adjacency[target].add(node_id)
    return adjacency, unresolved


def connected_components(node_ids: list[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Return connected components sorted by smallest node roster order."""
    if not node_ids:
        return []
    uf = _UnionFind(node_ids)
    for node_id, neighbors in adjacency.items():
        for neighbor in neighbors:
            uf.union(node_id, neighbor)
    groups: dict[str, list[str]] = defaultdict(list)
    for node_id in node_ids:
        groups[uf.find(node_id)].append(node_id)
    return [sorted(members) for members in groups.values()]


def topological_order(
    members: list[str],
    adjacency: dict[str, set[str]],
    records_by_node: dict[str, dict[str, Any]],
    title_index: dict[str, list[str]],
    roster_by_node: dict[str, dict[str, Any]],
) -> list[str]:
    """Order quests in a component using prev/next direction when possible."""
    member_set = set(members)
    indegree: dict[str, int] = {node_id: 0 for node_id in members}
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in members}
    for node_id in members:
        record = records_by_node.get(node_id, {})
        roster = roster_by_node.get(node_id, {})
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
                outgoing[prev_id].add(node_id)
                indegree[node_id] += 1
        for next_title in record.get("next", []):
            next_id = resolve_title_to_node_id(
                str(next_title),
                title_index=title_index,
                prefer_faction=faction,
                records_by_node=records_by_node,
                roster_by_node=roster_by_node,
            )
            if next_id and next_id in member_set:
                outgoing[node_id].add(next_id)
                indegree[next_id] += 1
    queue = deque(sorted(node_id for node_id in members if indegree[node_id] == 0))
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(ordered) != len(members):
        remaining = [node_id for node_id in members if node_id not in ordered]
        ordered.extend(sorted(remaining))
    return ordered


def _component_reputation_orgs(
    members: list[str], records_by_node: dict[str, dict[str, Any]]
) -> set[str]:
    orgs: set[str] = set()
    for node_id in members:
        org = str(records_by_node.get(node_id, {}).get("reputation_org", "")).strip()
        if org:
            orgs.add(org)
    return orgs


def _components_share_chain_bridge(
    left: list[str],
    right: list[str],
    adjacency: dict[str, set[str]],
) -> bool:
    left_set = set(left)
    right_set = set(right)
    for node_id in left:
        if adjacency.get(node_id, set()) & right_set:
            return True
    for node_id in right:
        if adjacency.get(node_id, set()) & left_set:
            return True
    return False


def merge_org_bridged_components(
    components: list[list[str]],
    *,
    adjacency: dict[str, set[str]],
    records_by_node: dict[str, dict[str, Any]],
) -> list[list[str]]:
    """Merge components only when they share reputation_org AND a chain edge."""
    merged = [list(members) for members in components]
    changed = True
    while changed:
        changed = False
        next_groups: list[list[str]] = []
        used = [False] * len(merged)
        for index, members in enumerate(merged):
            if used[index]:
                continue
            current = list(members)
            used[index] = True
            for other_index in range(index + 1, len(merged)):
                if used[other_index]:
                    continue
                other = merged[other_index]
                left_orgs = _component_reputation_orgs(current, records_by_node)
                right_orgs = _component_reputation_orgs(other, records_by_node)
                if not left_orgs or not right_orgs or left_orgs.isdisjoint(right_orgs):
                    continue
                if _components_share_chain_bridge(current, other, adjacency):
                    current.extend(other)
                    used[other_index] = True
                    changed = True
            next_groups.append(sorted(set(current)))
        merged = next_groups
    return merged


def _assign_faction_subclusters(
    members: list[str],
    *,
    adjacency: dict[str, set[str]],
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Split a component into alliance/horde/shared subclusters."""
    factions: dict[str, str] = {}
    for node_id in members:
        record = records_by_node.get(node_id, {})
        roster = roster_by_node.get(node_id, {})
        factions[node_id] = _record_faction(record, roster)

    present = {factions[node_id] for node_id in members}
    has_alliance = "alliance" in present
    has_horde = "horde" in present
    if not (has_alliance and has_horde):
        dominant = "alliance" if has_alliance else "horde" if has_horde else "shared"
        return {dominant: members}

    buckets: dict[str, list[str]] = {"alliance": [], "horde": [], "shared": []}
    assigned: set[str] = set()
    for faction in ("alliance", "horde"):
        seeds = [node_id for node_id in members if factions.get(node_id) == faction]
        queue = deque(sorted(seeds))
        while queue:
            node_id = queue.popleft()
            if node_id in assigned:
                continue
            assigned.add(node_id)
            buckets[faction].append(node_id)
            for neighbor in adjacency.get(node_id, set()):
                if neighbor not in members or neighbor in assigned:
                    continue
                neighbor_faction = factions.get(neighbor, "shared")
                if neighbor_faction in {faction, "shared"}:
                    queue.append(neighbor)
    for node_id in members:
        if node_id in assigned:
            continue
        buckets["shared"].append(node_id)
        assigned.add(node_id)

    return {key: sorted(value) for key, value in buckets.items() if value}


def _infer_cluster_title(
    members: list[str],
    *,
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
    faction: str,
) -> str:
    titles: list[str] = []
    for node_id in members:
        roster = roster_by_node.get(node_id, {})
        record = records_by_node.get(node_id, {})
        title = str(record.get("quest_title", "") or roster.get("title", "")).strip()
        if title:
            titles.append(title.lower())
        location = str(record.get("start_location", "")).strip()
        if location:
            titles.append(location.lower())
    blob = " ".join(titles)
    for keyword, label in _TITLE_KEYWORD_HINTS:
        if keyword in blob:
            if faction == "alliance":
                return f"{label} (Alliance)"
            if faction == "horde":
                return f"{label} (Horde)"
            return label

    org_counts: dict[str, int] = defaultdict(int)
    for node_id in members:
        org = str(records_by_node.get(node_id, {}).get("reputation_org", "")).strip()
        if org:
            org_counts[org] += 1
    if org_counts:
        dominant_org = sorted(org_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return dominant_org

    for node_id in members:
        location = str(records_by_node.get(node_id, {}).get("start_location", "")).strip()
        if location:
            return location
        category = str(records_by_node.get(node_id, {}).get("category", "")).strip()
        if category:
            return category

    first = roster_by_node.get(members[0], {})
    return str(first.get("title", "Questline"))


def _cluster_id_from_title(title: str, faction: str) -> str:
    slug = _slugify(title)
    if faction in {"alliance", "horde"} and f"-{faction}" not in slug:
        slug = f"{slug}-{faction}"
    return slug or _ORPHAN_CLUSTER_ID


def _split_oversized_subcomponents(
    members: list[str],
    adjacency: dict[str, set[str]],
    *,
    records_by_node: dict[str, dict[str, Any]],
    title_index: dict[str, list[str]],
    roster_by_node: dict[str, dict[str, Any]],
) -> list[list[str]]:
    if len(members) <= _MAX_CLUSTER_QUESTS:
        return [members]
    subcomponents = connected_components(members, adjacency)
    if len(subcomponents) > 1:
        return subcomponents
    ordered = topological_order(
        members,
        adjacency,
        records_by_node,
        title_index,
        roster_by_node,
    )
    segments: list[list[str]] = []
    for start in range(0, len(ordered), _MAX_CLUSTER_QUESTS):
        segments.append(ordered[start : start + _MAX_CLUSTER_QUESTS])
    return segments


def cluster_zone_questlines(
    *,
    zone_id: str,
    roster_rows: list[dict[str, Any]],
    quest_records: list[dict[str, Any]],
    storyline_html: str = "",
    zone_name: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Cluster flat roster rows using QuestRecord chain + narrative signals."""
    _ = storyline_html, zone_name
    quest_rows = [dict(row) for row in roster_rows if str(row.get("node_type", "")) == "quest"]
    non_quest_rows = [dict(row) for row in roster_rows if str(row.get("node_type", "")) != "quest"]
    if not quest_rows:
        return roster_rows, [], 0

    records_by_node: dict[str, dict[str, Any]] = {}
    for record in quest_records:
        if str(record.get("zone_id", "")).strip() != zone_id:
            continue
        if not record.get("has_questbox", True):
            continue
        node_id = str(record.get("node_id", "")).strip()
        if node_id:
            records_by_node[node_id] = record

    roster_by_node = {str(row.get("node_id", "")): row for row in quest_rows if row.get("node_id")}
    node_ids = sorted(
        roster_by_node,
        key=lambda node_id: int(roster_by_node[node_id].get("order_in_cluster", 0) or 0),
    )
    title_index = _build_title_index(quest_rows, records_by_node)
    adjacency, unresolved_edges = build_chain_adjacency(
        node_ids=node_ids,
        records_by_node=records_by_node,
        roster_by_node=roster_by_node,
        title_index=title_index,
    )

    components = connected_components(node_ids, adjacency)
    if not components:
        components = [[node_id] for node_id in node_ids]
    components = merge_org_bridged_components(
        components,
        adjacency=adjacency,
        records_by_node=records_by_node,
    )

    cluster_assignments: list[tuple[str, str, str, list[str]]] = []
    for component in components:
        if not component:
            continue
        subclusters = _assign_faction_subclusters(
            component,
            adjacency=adjacency,
            records_by_node=records_by_node,
            roster_by_node=roster_by_node,
        )
        for faction, members in subclusters.items():
            parts = _split_oversized_subcomponents(
                members,
                adjacency,
                records_by_node=records_by_node,
                title_index=title_index,
                roster_by_node=roster_by_node,
            )
            for part_index, part in enumerate(parts, start=1):
                title = _infer_cluster_title(
                    part,
                    records_by_node=records_by_node,
                    roster_by_node=roster_by_node,
                    faction=faction,
                )
                cluster_id = _cluster_id_from_title(title, faction)
                if len(parts) > 1:
                    cluster_id = f"{cluster_id}-part-{part_index}"
                    if part_index > 1:
                        title = f"{title} (Part {part_index})"
                cluster_assignments.append((cluster_id, title, faction, part))

    cluster_assignments.sort(
        key=lambda item: (
            min(int(roster_by_node[node_id].get("order_in_cluster", 0) or 0) for node_id in item[3]),
            item[0],
        )
    )

    updated_rows: list[dict[str, Any]] = []
    for cluster_order, (cluster_id, cluster_title, faction, members) in enumerate(cluster_assignments, start=1):
        ordered_members = topological_order(
            members,
            adjacency,
            records_by_node,
            title_index,
            roster_by_node,
        )
        for order_in_cluster, node_id in enumerate(ordered_members, start=1):
            row = dict(roster_by_node[node_id])
            row["cluster_id"] = cluster_id
            row["cluster_title"] = cluster_title
            row["cluster_order"] = cluster_order
            row["order_in_cluster"] = order_in_cluster
            row["faction_binding"] = faction
            updated_rows.append(row)

    layered = split_by_level_band(updated_rows)
    final_summaries = _summaries_from_rows(zone_id, layered, records_by_node=records_by_node)
    return non_quest_rows + layered, final_summaries, unresolved_edges


def _summaries_from_rows(
    zone_id: str,
    rows: list[dict[str, Any]],
    *,
    records_by_node: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("node_type", "")) != "quest":
            continue
        grouped[str(row.get("cluster_id", ""))].append(row)
    summaries: list[dict[str, Any]] = []
    for cluster_id, quests in sorted(grouped.items()):
        if not cluster_id:
            continue
        quests.sort(key=lambda row: int(row.get("order_in_cluster", 0) or 0))
        faction = str(quests[0].get("faction_binding", "shared"))
        reputation_orgs = sorted(
            {
                str(records_by_node.get(str(row.get("node_id", "")), {}).get("reputation_org", "")).strip()
                for row in quests
            }
            - {""}
        )
        summaries.append(
            {
                "zone_id": zone_id,
                "cluster_id": cluster_id,
                "title": str(quests[0].get("cluster_title", cluster_id)),
                "faction": faction,
                "quest_count": len(quests),
                "reputation_orgs": reputation_orgs,
                "quest_node_ids": [str(row.get("node_id", "")) for row in quests if row.get("node_id")],
                "algorithm_version": _ALGORITHM_VERSION,
            }
        )
    return summaries
