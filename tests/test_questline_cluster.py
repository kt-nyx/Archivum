from __future__ import annotations

import json
from pathlib import Path

from pipeline.contracts.models import QuestlineClusterSummary
from pipeline.discovery.questline_cluster import (
    _MAX_CLUSTER_QUESTS,
    build_chain_adjacency,
    cluster_zone_questlines,
    connected_components,
    merge_org_bridged_components,
    normalize_quest_title,
    resolve_title_to_node_id,
    topological_order,
)

FIXTURE_DIR = Path("tests/fixtures/clustering")
ZONE_ID = "zone-western-plaguelands"


def _load_wpl_fixture() -> tuple[list[dict], list[dict]]:
    roster = json.loads(
        (FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text(encoding="utf-8")
    )
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return roster, records


def _quest_row(
    node_id: str,
    title: str,
    order: int,
    *,
    zone_id: str = "zone-example",
    faction: str = "shared",
    level: str = "[35-40]",
) -> dict:
    return {
        "zone_id": zone_id,
        "node_type": "quest",
        "cluster_id": "unclustered",
        "cluster_title": "",
        "cluster_order": 0,
        "order_in_cluster": order,
        "node_id": node_id,
        "title": title,
        "faction_binding": faction,
        "level_range": level,
        "source_link": f"/wiki/{title.replace(' ', '_')}",
    }


def _record(
    node_id: str,
    title: str,
    *,
    zone_id: str = "zone-example",
    faction: str = "shared",
    previous: list[str] | None = None,
    next_quests: list[str] | None = None,
    org: str = "",
) -> dict:
    return {
        "zone_id": zone_id,
        "node_id": node_id,
        "quest_title": title,
        "source_link": f"/wiki/{title.replace(' ', '_')}",
        "has_questbox": True,
        "faction": faction,
        "previous": previous or [],
        "next": next_quests or [],
        "reputation_org": org,
        "category": "Example Zone",
        "start_location": "",
        "description": "",
    }


def test_normalize_quest_title_strips_level_prefix() -> None:
    assert normalize_quest_title("[15-30] The Battle for Andorhal") == "the battle for andorhal"
    assert normalize_quest_title("Go Fletch!") == "go fletch"


def test_resolve_title_to_node_id_prefers_faction_match() -> None:
    roster = [
        _quest_row("quest-a", "Patrol Duty", 1, faction="alliance"),
        _quest_row("quest-h", "Patrol Duty", 2, faction="horde"),
    ]
    records = [
        _record("quest-a", "Patrol Duty", faction="alliance"),
        _record("quest-h", "Patrol Duty", faction="horde"),
    ]
    records_by_node = {row["node_id"]: row for row in records}
    roster_by_node = {row["node_id"]: row for row in roster}
    title_index = {"patrol duty": ["quest-a", "quest-h"]}
    assert (
        resolve_title_to_node_id(
            "Patrol Duty",
            title_index=title_index,
            prefer_faction="horde",
            records_by_node=records_by_node,
            roster_by_node=roster_by_node,
        )
        == "quest-h"
    )


def test_resolve_title_uses_fuzzy_fallback_for_near_miss() -> None:
    title_index = {"the battle for andorhal": ["quest-andorhal"]}
    resolved = resolve_title_to_node_id(
        "The Battle for Andorhaal",  # doubled 'a' — exact normalization still misses
        title_index=title_index,
        prefer_faction="shared",
        records_by_node={},
        roster_by_node={},
    )
    assert resolved == "quest-andorhal"


def test_resolve_title_fuzzy_rejects_distinct_sibling() -> None:
    title_index = {"the battle for andorhal": ["quest-andorhal"]}
    resolved = resolve_title_to_node_id(
        "The Battle for Darrowshire",  # distinct quest, well below the cutoff
        title_index=title_index,
        prefer_faction="shared",
        records_by_node={},
        roster_by_node={},
    )
    assert resolved is None


def test_section_comembership_merges_unchained_section_members() -> None:
    """Quests sharing a real storyline heading section merge even without a prev/next edge."""
    section = "the-battle-for-andorhal"
    roster = [_quest_row("q1", "Alpha", 1), _quest_row("q2", "Beta", 2)]
    for row in roster:
        row["cluster_id"] = section
    record_a = _record("q1", "Alpha")
    record_a["category"] = "Region A"
    record_b = _record("q2", "Beta")
    record_b["category"] = "Region B"
    rows, summaries, _unresolved = cluster_zone_questlines(
        zone_id="zone-example",
        roster_rows=roster,
        quest_records=[record_a, record_b],
    )
    quest_clusters = {row["cluster_id"] for row in rows if row.get("node_type") == "quest"}
    assert len(quest_clusters) == 1
    assert len(summaries) == 1
    assert summaries[0]["quest_count"] == 2


def test_placeholder_section_keeps_unchained_quests_separate() -> None:
    """The default/placeholder section bucket must not seed co-membership edges."""
    # _quest_row defaults cluster_id to the placeholder 'unclustered'
    roster = [_quest_row("q1", "Alpha", 1), _quest_row("q2", "Beta", 2)]
    record_a = _record("q1", "Alpha")
    record_a["category"] = "Region A"
    record_b = _record("q2", "Beta")
    record_b["category"] = "Region B"
    rows, _summaries, _unresolved = cluster_zone_questlines(
        zone_id="zone-example",
        roster_rows=roster,
        quest_records=[record_a, record_b],
    )
    quest_clusters = {row["cluster_id"] for row in rows if row.get("node_type") == "quest"}
    assert len(quest_clusters) == 2


def test_chain_components_form_on_synthetic_three_quest_chain() -> None:
    roster = [
        _quest_row("q1", "Alpha", 1),
        _quest_row("q2", "Beta", 2),
        _quest_row("q3", "Gamma", 3),
    ]
    records = [
        _record("q1", "Alpha", next_quests=["Beta"]),
        _record("q2", "Beta", previous=["Alpha"], next_quests=["Gamma"]),
        _record("q3", "Gamma", previous=["Beta"]),
    ]
    records_by_node = {row["node_id"]: row for row in records}
    roster_by_node = {row["node_id"]: row for row in roster}
    title_index = {
        "alpha": ["q1"],
        "beta": ["q2"],
        "gamma": ["q3"],
    }
    adjacency, unresolved = build_chain_adjacency(
        node_ids=["q1", "q2", "q3"],
        records_by_node=records_by_node,
        roster_by_node=roster_by_node,
        title_index=title_index,
    )
    assert unresolved == 0
    components = connected_components(["q1", "q2", "q3"], adjacency)
    assert components == [["q1", "q2", "q3"]]
    ordered = topological_order(
        ["q1", "q2", "q3"],
        adjacency,
        records_by_node,
        title_index,
        roster_by_node,
    )
    assert ordered == ["q1", "q2", "q3"]


def test_faction_split_separates_mixed_andorhal_hub() -> None:
    roster = [
        _quest_row("qa", "Alliance Lead", 1, faction="alliance"),
        _quest_row("qh", "Horde Lead", 2, faction="horde"),
        _quest_row("qs", "Shared Hub", 3, faction="shared"),
    ]
    records = [
        _record("qa", "Alliance Lead", faction="alliance", next_quests=["Shared Hub"]),
        _record("qh", "Horde Lead", faction="horde", next_quests=["Shared Hub"]),
        _record("qs", "Shared Hub", faction="shared", previous=["Alliance Lead", "Horde Lead"]),
    ]
    rows, summaries, _unresolved = cluster_zone_questlines(
        zone_id="zone-example",
        roster_rows=roster,
        quest_records=records,
    )
    cluster_ids = {row["cluster_id"] for row in rows}
    assert len(cluster_ids) == 2
    factions = {summary["faction"] for summary in summaries}
    assert factions == {"alliance", "horde"}


def test_conservative_merge_does_not_join_same_org_without_bridge() -> None:
    components = [["a1", "a2"], ["b1", "b2"]]
    adjacency = {
        "a1": {"a2"},
        "a2": {"a1"},
        "b1": {"b2"},
        "b2": {"b1"},
    }
    records_by_node = {
        "a1": {"reputation_org": "Argent Crusade"},
        "a2": {"reputation_org": "Argent Crusade"},
        "b1": {"reputation_org": "Argent Crusade"},
        "b2": {"reputation_org": "Argent Crusade"},
    }
    merged = merge_org_bridged_components(
        components,
        adjacency=adjacency,
        records_by_node=records_by_node,
    )
    assert len(merged) == 2


def test_cluster_size_cap_splits_long_chain() -> None:
    count = _MAX_CLUSTER_QUESTS + 2
    roster = [_quest_row(f"q{i}", f"Quest {i}", i) for i in range(1, count + 1)]
    records = []
    for index in range(1, count + 1):
        previous = [f"Quest {index - 1}"] if index > 1 else []
        next_quests = [f"Quest {index + 1}"] if index < count else []
        records.append(
            _record(f"q{index}", f"Quest {index}", previous=previous, next_quests=next_quests)
        )
    rows, summaries, _unresolved = cluster_zone_questlines(
        zone_id="zone-example",
        roster_rows=roster,
        quest_records=records,
    )
    sizes = [summary["quest_count"] for summary in summaries]
    assert max(sizes) <= _MAX_CLUSTER_QUESTS
    assert len(summaries) >= 2


def test_wpl_fixture_produces_distinct_storyline_clusters() -> None:
    roster, records = _load_wpl_fixture()
    rows, summaries, _unresolved = cluster_zone_questlines(
        zone_id=ZONE_ID,
        roster_rows=roster,
        quest_records=records,
        zone_name="Western Plaguelands",
    )
    quest_rows = [row for row in rows if row.get("node_type") == "quest"]
    cluster_ids = {row["cluster_id"] for row in quest_rows}
    titles_by_cluster = {row["cluster_id"]: row["cluster_title"] for row in quest_rows}

    assert "unclustered" not in cluster_ids
    assert len(cluster_ids) >= 5
    assert all(summary["quest_count"] <= _MAX_CLUSTER_QUESTS for summary in summaries)
    assert len(quest_rows) < len(roster) or len(cluster_ids) >= 5

    def cluster_with_keyword(keyword: str) -> set[str]:
        return {
            cluster_id
            for cluster_id, title in titles_by_cluster.items()
            if keyword.lower() in title.lower()
        }

    andorhal_alliance = cluster_with_keyword("andorhal") & {
        cid for cid, title in titles_by_cluster.items() if "alliance" in title.lower()
    }
    andorhal_horde = cluster_with_keyword("andorhal") & {
        cid for cid, title in titles_by_cluster.items() if "horde" in title.lower()
    }
    assert andorhal_alliance
    assert andorhal_horde
    assert andorhal_alliance.isdisjoint(andorhal_horde)

    mender = cluster_with_keyword("mender") | cluster_with_keyword("cenarion")
    hearthglen = cluster_with_keyword("hearthglen")
    gahrron = cluster_with_keyword("gahrron")
    northridge = cluster_with_keyword("northridge")
    assert mender
    assert hearthglen
    assert gahrron
    assert northridge
    assert mender.isdisjoint(andorhal_alliance | andorhal_horde)

    for summary in summaries:
        QuestlineClusterSummary.model_validate(summary)
