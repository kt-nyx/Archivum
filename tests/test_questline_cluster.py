from __future__ import annotations

import json
from pathlib import Path

from pipeline.contracts.models import QuestlineClusterSummary
from pipeline.discovery.questline_cluster import (
    _MAX_CLUSTER_QUESTS,
    build_chain_adjacency,
    cluster_zone_questlines,
    connected_components,
    materialize_faction_variant_beats,
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


def test_distinct_chains_sharing_rep_org_do_not_collapse() -> None:
    """Two unrelated chains with the same reputation_org and no start_location must stay apart.

    This reproduces the live WPL regression: with start_location empty, cluster identity used
    to fall back to reputation_org, so two distinct graph components ("Argent Crusade") slugged
    to one cluster_id and re-merged in _summaries_from_rows. Identity is now structural.
    """
    roster = [
        _quest_row("quest-a1", "Alpha One", 1),
        _quest_row("quest-a2", "Alpha Two", 2),
        _quest_row("quest-b1", "Bravo One", 3),
        _quest_row("quest-b2", "Bravo Two", 4),
    ]
    records = [
        _record("quest-a1", "Alpha One", next_quests=["Alpha Two"], org="Argent Crusade"),
        _record("quest-a2", "Alpha Two", previous=["Alpha One"], org="Argent Crusade"),
        _record("quest-b1", "Bravo One", next_quests=["Bravo Two"], org="Argent Crusade"),
        _record("quest-b2", "Bravo Two", previous=["Bravo One"], org="Argent Crusade"),
    ]
    rows, summaries, _unresolved = cluster_zone_questlines(
        zone_id="zone-example",
        roster_rows=roster,
        quest_records=records,
    )
    cluster_ids = {row["cluster_id"] for row in rows if row.get("node_type") == "quest"}
    assert len(cluster_ids) == 2, cluster_ids
    assert len(summaries) == 2
    assert all(summary["quest_count"] == 2 for summary in summaries)
    # rep-org is retained as an attribute, never as the identity title.
    assert all("Argent Crusade" not in summary["title"] for summary in summaries)
    assert all(summary["reputation_orgs"] == ["Argent Crusade"] for summary in summaries)


def _load_wpl_registry_arcs() -> dict[str, list[str]]:
    """Return {arc_title: [chain_ref node_ids]} from the canonical questline oracle."""
    registry = json.loads(
        (Path("tests/fixtures/pilot/western_plaguelands_questline_registry.json")).read_text(
            encoding="utf-8"
        )
    )
    return {arc["title"]: list(arc.get("chain_refs", [])) for arc in registry["included_arcs"]}


def test_materialize_variant_beats_splits_stranded_shared_node() -> None:
    roster = [
        _quest_row("quest-a1", "Alpha One", 1, faction="alliance"),
        _quest_row("quest-h1", "Bravo One", 2, faction="horde"),
        _quest_row("quest-combat-training", "Combat Training", 3, faction="shared"),
    ]
    records = [
        _record(
            "quest-a1", "Alpha One", faction="alliance", next_quests=["Combat Training (Alliance)"]
        ),
        _record("quest-h1", "Bravo One", faction="horde", next_quests=["Combat Training (Horde)"]),
        # No record for the shared Combat Training node -> stranded storyline placeholder.
    ]
    new_roster, new_records = materialize_faction_variant_beats(
        roster, records, zone_id="zone-example"
    )
    roster_ids = {row["node_id"] for row in new_roster}
    assert "quest-combat-training" not in roster_ids
    assert {"quest-combat-training-alliance", "quest-combat-training-horde"} <= roster_ids
    by_id = {row["node_id"]: row for row in new_roster}
    assert by_id["quest-combat-training-alliance"]["faction_binding"] == "alliance"
    assert by_id["quest-combat-training-horde"]["title"] == "Combat Training (Horde)"
    variant_records = {r["node_id"] for r in new_records if r.get("has_questbox")}
    assert {"quest-combat-training-alliance", "quest-combat-training-horde"} <= variant_records


def test_materialize_variant_beats_leaves_genuine_shared_quest_untouched() -> None:
    # A shared node that owns a real questbox record is a genuine shared quest, not a stranded
    # placeholder; it must not be split even if referenced with a faction suffix somewhere.
    roster = [
        _quest_row("quest-a1", "Alpha One", 1, faction="alliance"),
        _quest_row("quest-shared", "Shared Beat", 2, faction="shared"),
    ]
    records = [
        _record(
            "quest-a1", "Alpha One", faction="alliance", next_quests=["Shared Beat (Alliance)"]
        ),
        _record("quest-shared", "Shared Beat", faction="shared"),  # has_questbox=True
    ]
    new_roster, _new_records = materialize_faction_variant_beats(
        roster, records, zone_id="zone-example"
    )
    roster_ids = {row["node_id"] for row in new_roster}
    assert "quest-shared" in roster_ids
    assert "quest-shared-alliance" not in roster_ids


def test_wpl_fixture_clusters_match_registry_arc_separation() -> None:
    """Real-data clustering must keep the canonical storyline arcs apart (Fix A).

    The fixture is distilled from the live ``test-run-wpl-1`` discovery artifacts
    (`scripts/distill_clustering_fixture.py`), so this asserts the *component layer*
    invariants against the questline registry oracle, not the synthetic ">=5 clusters"
    heuristic that passed while the live run was wrong. The final 3-card grouping is a
    later layer (significance/cluster-layers) and is out of scope here.
    """
    roster, records = _load_wpl_fixture()
    rows, summaries, _unresolved = cluster_zone_questlines(
        zone_id=ZONE_ID,
        roster_rows=roster,
        quest_records=records,
        zone_name="Western Plaguelands",
    )
    quest_rows = [row for row in rows if row.get("node_type") == "quest"]
    cluster_by_node = {row["node_id"]: row["cluster_id"] for row in quest_rows}
    cluster_ids = set(cluster_by_node.values())
    faction_by_node = {rec["node_id"]: rec.get("faction", "") for rec in records}

    assert "unclustered" not in cluster_ids

    # 1. No reputation-org mega-cluster: the old bug fused 21 quests into one "Argent
    #    Crusade" cluster. Real components stay well under the size cap.
    assert all(summary["quest_count"] <= _MAX_CLUSTER_QUESTS for summary in summaries)
    assert max(summary["quest_count"] for summary in summaries) <= 12

    # 2. Reputation org is an attribute, never the cluster identity/title.
    for summary in summaries:
        for org in ("Argent Crusade", "Undercity", "Stormwind", "Cenarion"):
            assert org not in summary["title"], summary["title"]

    # 3. Distinct registry arcs never share a cluster (no cross-arc bleed). Exclude
    #    combat-training: it is the cross-faction shared beat both arcs legitimately claim
    #    and is currently an isolated singleton (#11, asserted separately below).
    arcs = _load_wpl_registry_arcs()
    arc_clusters: dict[str, set[str]] = {}
    for title, refs in arcs.items():
        arc_clusters[title] = {
            cluster_by_node[ref]
            for ref in refs
            if ref in cluster_by_node and ref != "quest-combat-training"
        }
    arc_titles = list(arc_clusters)
    for i in range(len(arc_titles)):
        for j in range(i + 1, len(arc_titles)):
            left, right = arc_clusters[arc_titles[i]], arc_clusters[arc_titles[j]]
            assert left.isdisjoint(right), (arc_titles[i], arc_titles[j], left & right)

    # 4. The Andorhal Alliance and Horde entry quests anchor different, faction-pure
    #    clusters (the live run fragmented and cross-wired these).
    alliance_entry = cluster_by_node["quest-heros-call-western-plaguelands"]
    horde_entry = cluster_by_node["quest-warchiefs-command-western-plaguelands"]
    assert alliance_entry != horde_entry
    for node_id, cluster_id in cluster_by_node.items():
        if cluster_id in (alliance_entry, horde_entry):
            faction = faction_by_node.get(node_id, "")
            if not faction or faction == "shared":
                continue
            expected = "alliance" if cluster_id == alliance_entry else "horde"
            assert faction == expected, (node_id, cluster_id, faction)

    for summary in summaries:
        QuestlineClusterSummary.model_validate(summary)


def test_wpl_combat_training_splits_into_per_faction_variants() -> None:
    """Fix A step 4 / Option C: the same-name cross-faction beat is materialized per faction.

    ``Combat Training`` is two distinct same-named quests the storyline lists once as a single
    stranded ``shared`` node (no questbox); each faction's chain references it as
    "Combat Training (Alliance)" / "(Horde)". ``materialize_faction_variant_beats`` replaces the
    stranded shared node with one faction-bound variant per referencing faction, each joining
    its own faction's arc (so it can reach both faction cards) without a cross-faction edge that
    would fuse the two Andorhal arcs into one component.

    NOTE: reaching *both rendered cards* additionally depends on the card layer, which currently
    selects a single cluster per multi-part arc; this test pins the clustering-layer guarantee.
    """
    roster, records = _load_wpl_fixture()
    rows, _summaries, _unresolved = cluster_zone_questlines(
        zone_id=ZONE_ID,
        roster_rows=roster,
        quest_records=records,
        zone_name="Western Plaguelands",
    )
    quest_rows = [row for row in rows if row.get("node_type") == "quest"]
    cluster_by_node = {row["node_id"]: row["cluster_id"] for row in quest_rows}
    faction_by_node = {row["node_id"]: row.get("faction_binding") for row in quest_rows}

    # The stranded shared node is gone, replaced by two faction-bound variants.
    assert "quest-combat-training" not in cluster_by_node
    assert faction_by_node.get("quest-combat-training-alliance") == "alliance"
    assert faction_by_node.get("quest-combat-training-horde") == "horde"

    # Each variant joins its faction-chain neighbour's cluster (the next-ref now resolves).
    assert (
        cluster_by_node["quest-combat-training-alliance"]
        == cluster_by_node["quest-this-is-our-army"]
    )
    assert (
        cluster_by_node["quest-combat-training-horde"]
        == cluster_by_node["quest-when-death-is-not-enough"]
    )

    # The split must NOT fuse the two faction arcs: the variants live in different clusters and
    # no single cluster mixes both faction variants.
    assert (
        cluster_by_node["quest-combat-training-alliance"]
        != cluster_by_node["quest-combat-training-horde"]
    )
