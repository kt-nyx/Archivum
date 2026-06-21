"""Graph-based questline clustering (S5 re-founding).

Single home for post-traverse questline clustering. Quests are clustered from two
**structural** edge sources — QuestRecord prev/next chains and co-membership in the same
storyline-page heading section (parsed via WS-A) — using ``networkx`` for connected
components and ``graphlib.TopologicalSorter`` for in-cluster ordering. Title resolution
falls back to ``rapidfuzz`` when an exact normalized title misses. Conservative org-bridged
merges, faction splits, and size guardrails keep clusters from collapsing into a mega-cluster
or fragmenting. Faction is a derived node attribute (section icon / record), never a keyword
guess (WS-C). The layered transforms (``split_by_faction`` / ``split_by_level_band`` /
``infer_hub_titles`` / ``apply_cluster_layers``) previously living in ``questline_clustering``
are consolidated here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from graphlib import CycleError, TopologicalSorter
from typing import Any

import networkx as nx
from rapidfuzz import fuzz, process

from pipeline.common.text_ids import slugify
from pipeline.discovery.storyline_html import anchor_index_map, collect_heading_events

_ALGORITHM_VERSION = "v2-graph-clusterer"
_ORPHAN_CLUSTER_ID = "orphan"
_MAX_CLUSTER_QUESTS = 15
_GENERIC_CLUSTER_TITLES = frozenset({"main storylines", "main storyline", ""})
# Section ids that carry no real heading signal: they must not seed co-membership edges
# (otherwise every default-bucket quest would merge into one component). Any id beginning
# with ``cluster-main`` is treated the same way.
_PLACEHOLDER_SECTION_IDS = frozenset(
    {"", "unclustered", "cluster-main", "main-storylines", "main-storyline", "orphan"}
)
# rapidfuzz cutoff for the title-resolution fallback. High on purpose: titles are already
# normalized (lowercased, level-prefix + punctuation stripped), so the only legitimate misses
# are tiny spelling/spacing variants — not distinct "Battle for X" siblings.
_FUZZY_TITLE_CUTOFF = 93.0

_LEVEL_PREFIX_RE = re.compile(r"^\[[0-9]+(?:-[0-9]+)?\]\s*")
# Strip wiki disambiguation parentheticals (e.g. "Stormwind (faction)" -> "Stormwind") so
# a reputation-org page name can't carry a "(faction)" suffix into a cluster title/id.
_DISAMBIG_PARENS_RE = re.compile(r"\s*\((?:faction|quest|disambiguation)\)\s*$", re.IGNORECASE)


def _slugify(text: str) -> str:
    return slugify(text) or "cluster-main"


def _is_generic_cluster_title(title: str) -> bool:
    return title.strip().lower() in _GENERIC_CLUSTER_TITLES


def _strip_disambiguation(title: str) -> str:
    return _DISAMBIG_PARENS_RE.sub("", title).strip()


def normalize_quest_title(title: str) -> str:
    """Normalize a quest title for prev/next resolution (strip level prefixes)."""
    cleaned = _LEVEL_PREFIX_RE.sub("", title.strip())
    cleaned = re.sub(r"[^\w\s'-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


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


def _fuzzy_title_candidates(key: str, title_index: dict[str, list[str]]) -> list[str]:
    """Resolve a normalized title to candidates via rapidfuzz when the exact key misses."""
    if not title_index:
        return []
    match = process.extractOne(
        key,
        list(title_index.keys()),
        scorer=fuzz.ratio,
        score_cutoff=_FUZZY_TITLE_CUTOFF,
    )
    if match is None:
        return []
    return title_index.get(str(match[0]), [])


def resolve_title_to_node_id(
    title: str,
    *,
    title_index: dict[str, list[str]],
    prefer_faction: str,
    records_by_node: dict[str, dict[str, Any]],
    roster_by_node: dict[str, dict[str, Any]],
) -> str | None:
    """Resolve a prev/next title string to a roster node_id (exact, then fuzzy)."""
    key = normalize_quest_title(title)
    if not key:
        return None
    candidates = title_index.get(key) or _fuzzy_title_candidates(key, title_index)
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


def add_section_comembership_edges(
    adjacency: dict[str, set[str]],
    quest_rows: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Connect quests that share a real storyline heading section (WS-A structural signal).

    Each non-placeholder section's members are linked to the section's lexicographically
    smallest member (a star), making them one component even when their prev/next titles
    failed to resolve. Placeholder/default-bucket sections are skipped so the signal only
    *recovers* orphaned section members, never collapses the default bucket.
    """
    sections: dict[str, list[str]] = defaultdict(list)
    for row in quest_rows:
        node_id = str(row.get("node_id", "")).strip()
        if not node_id or node_id not in adjacency:
            continue
        section_id = str(row.get("cluster_id", "")).strip().lower()
        if not section_id or section_id in _PLACEHOLDER_SECTION_IDS:
            continue
        if section_id.startswith("cluster-main"):
            continue
        sections[section_id].append(node_id)
    for members in sections.values():
        if len(members) < 2:
            continue
        anchor = min(members)
        for node_id in members:
            if node_id == anchor:
                continue
            adjacency[anchor].add(node_id)
            adjacency[node_id].add(anchor)
    return adjacency


def connected_components(node_ids: list[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Return connected components (networkx), each sorted, ordered by smallest node id."""
    if not node_ids:
        return []
    node_set = set(node_ids)
    graph = nx.Graph()
    graph.add_nodes_from(node_ids)
    for node_id in node_ids:
        for neighbor in adjacency.get(node_id, set()):
            if neighbor in node_set:
                graph.add_edge(node_id, neighbor)
    components = [sorted(component) for component in nx.connected_components(graph)]
    components.sort(key=lambda members: members[0] if members else "")
    return components


def topological_order(
    members: list[str],
    adjacency: dict[str, set[str]],
    records_by_node: dict[str, dict[str, Any]],
    title_index: dict[str, list[str]],
    roster_by_node: dict[str, dict[str, Any]],
) -> list[str]:
    """Order quests in a component using prev/next direction (graphlib), then sort the rest.

    ``adjacency`` is unused (kept for call-site compatibility); ordering derives from the
    directed prev/next edges. Cyclic or unreachable nodes fall back to a stable sort.
    """
    member_set = set(members)
    predecessors: dict[str, set[str]] = {node_id: set() for node_id in members}
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
                predecessors[node_id].add(prev_id)
        for next_title in record.get("next", []):
            next_id = resolve_title_to_node_id(
                str(next_title),
                title_index=title_index,
                prefer_faction=faction,
                records_by_node=records_by_node,
                roster_by_node=roster_by_node,
            )
            if next_id and next_id in member_set:
                predecessors[next_id].add(node_id)

    sorter: TopologicalSorter[str] = TopologicalSorter(predecessors)
    try:
        sorter.prepare()
    except CycleError:
        return sorted(members)
    ordered: list[str] = []
    while sorter.is_active():
        for node_id in sorted(sorter.get_ready()):
            ordered.append(node_id)
            sorter.done(node_id)
    if len(ordered) != len(members):
        ordered.extend(sorted(node_id for node_id in members if node_id not in ordered))
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
    member_set = set(members)
    for faction in ("alliance", "horde"):
        seeds = [node_id for node_id in members if factions.get(node_id) == faction]
        # Walk shared/same-faction neighbours from each faction seed (deterministic order).
        frontier = sorted(seeds)
        while frontier:
            node_id = frontier.pop(0)
            if node_id in assigned:
                continue
            assigned.add(node_id)
            buckets[faction].append(node_id)
            for neighbor in sorted(adjacency.get(node_id, set())):
                if neighbor not in member_set or neighbor in assigned:
                    continue
                neighbor_faction = factions.get(neighbor, "shared")
                if neighbor_faction in {faction, "shared"}:
                    frontier.append(neighbor)
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
    """Derive a structural cluster title (no zone keyword tables).

    Preference order: a shared start location (hub name) -> a dominant reputation org for
    *multi-quest* clusters -> the first quest's title. Single-quest clusters never take an
    org name as their title, so unrelated breadcrumb singletons that merely share a
    reputation faction (e.g. "Stormwind (faction)") cannot collapse into one fake cluster.
    Wiki disambiguation suffixes are stripped from the result.
    """

    def _faction_tag(label: str) -> str:
        label = _strip_disambiguation(label) or "Questline"
        if faction == "alliance":
            return f"{label} (Alliance)"
        if faction == "horde":
            return f"{label} (Horde)"
        return label

    location_counts: dict[str, int] = defaultdict(int)
    for node_id in members:
        location = str(records_by_node.get(node_id, {}).get("start_location", "")).strip()
        if location:
            location_counts[location] += 1
    if location_counts:
        dominant_location = sorted(location_counts.items(), key=lambda item: (-item[1], item[0]))[
            0
        ][0]
        return _faction_tag(dominant_location)

    if len(members) > 1:
        org_counts: dict[str, int] = defaultdict(int)
        for node_id in members:
            org = str(records_by_node.get(node_id, {}).get("reputation_org", "")).strip()
            if org:
                org_counts[org] += 1
        if org_counts:
            dominant_org = sorted(org_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
            return _faction_tag(dominant_org)

    for node_id in members:
        category = str(records_by_node.get(node_id, {}).get("category", "")).strip()
        if category:
            return _faction_tag(category)

    first = roster_by_node.get(members[0], {})
    record_title = str(records_by_node.get(members[0], {}).get("quest_title", "")).strip()
    return _faction_tag(record_title or str(first.get("title", "Questline")))


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
    """Cluster flat roster rows using QuestRecord chains + storyline-section structure."""
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
    adjacency = add_section_comembership_edges(adjacency, quest_rows)

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
            min(
                int(roster_by_node[node_id].get("order_in_cluster", 0) or 0) for node_id in item[3]
            ),
            item[0],
        )
    )

    updated_rows: list[dict[str, Any]] = []
    for cluster_order, (cluster_id, cluster_title, faction, members) in enumerate(
        cluster_assignments, start=1
    ):
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
                str(
                    records_by_node.get(str(row.get("node_id", "")), {}).get("reputation_org", "")
                ).strip()
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
                "quest_node_ids": [
                    str(row.get("node_id", "")) for row in quests if row.get("node_id")
                ],
                "algorithm_version": _ALGORITHM_VERSION,
            }
        )
    return summaries


# ---------------------------------------------------------------------------
# Layered cluster transforms (consolidated from the former questline_clustering).
# ---------------------------------------------------------------------------


def infer_hub_titles(rows: list[dict[str, Any]], html: str) -> list[dict[str, Any]]:
    """Fill generic cluster titles from the nearest preceding storyline heading."""
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
        out["cluster_order"] = next(
            (index + 1 for index, item in enumerate(headings) if item[1] == active[1]), 1
        )
        out["heading_level"] = active[3]
        updated.append(out)
    return updated


def _cluster_groups(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
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


def split_by_faction(
    rows: list[dict[str, Any]], *, max_quests: int = _MAX_CLUSTER_QUESTS
) -> list[dict[str, Any]]:
    groups = _cluster_groups(rows)
    output: list[dict[str, Any]] = []
    non_quest = [dict(row) for row in rows if str(row.get("node_type", "")) != "quest"]
    for (zone_id, cluster_id), quests in sorted(groups.items()):
        bindings = {str(row.get("faction_binding", "shared")) for row in quests}
        mixed_faction = len({b for b in bindings if b in {"alliance", "horde"}}) > 1
        needs_split = len(quests) > max_quests or (mixed_faction and len(quests) >= 4)
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


def split_by_level_band(
    rows: list[dict[str, Any]], *, max_quests: int = _MAX_CLUSTER_QUESTS
) -> list[dict[str, Any]]:
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
