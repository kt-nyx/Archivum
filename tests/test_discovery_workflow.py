from __future__ import annotations

import json
from pathlib import Path

from pipeline.common.run_context import ensure_run_context
from pipeline.discovery.workflow import (
    _effective_section_slug,
    _section_role,
    run_discovery_workflow,
)

ZONE_ID = "zone-example"
ZONE_NAME = "Example Zone"
ZONE_WIKI = "Example_Zone"
INSTANCE_ID = "instance-example-dungeon"
INSTANCE_NAME = "Example Dungeon"


def test_effective_section_slug_inherits_history_for_unrecognized_subsection() -> None:
    # "The Scourging[edit]" classifies to "other" on its own; under a "History" parent
    # it must inherit history so the prose keeps its real narrative role (Fix B).
    assert _section_role("the_scourging_edit") == "other"
    assert _section_role("history") == "history"
    assert _effective_section_slug("the_scourging_edit", "history") == "history"
    assert _section_role(_effective_section_slug("the_scourging_edit", "history")) == "history"


def test_section_role_recognizes_era_headings_as_history() -> None:
    # Expansion-/era-named timeline sections are in-universe history even without a
    # "history"/"lore" token, so their prose keeps a real role instead of "other" (WS-1).
    assert _section_role("cataclysm_edit") == "history"
    assert _section_role("battle_for_azeroth") == "history"
    assert _section_role("legion") == "history"
    assert _section_role("mists_of_pandaria_edit") == "history"
    # Non-era unrecognized headings still fall through to "other".
    assert _section_role("rewards_edit") == "other"
    assert _section_role("external_links") == "other"


def test_effective_section_slug_keeps_recognized_leaf_and_rpg_parent() -> None:
    # A leaf that classifies on its own is never overridden by its parent.
    assert _effective_section_slug("notable_characters", "history") == "notable_characters"
    # An unrecognized leaf with an unrecognized parent stays as-is.
    assert _effective_section_slug("external_links", "navbox") == "external_links"
    # RPG parents stay RPG, so canon history is never polluted with RPG content.
    assert _section_role("the_grand_tour") == "other"
    assert _section_role(_effective_section_slug("the_grand_tour", "in_the_rpg")) == "in_the_rpg"


def test_discovery_workflow_emits_required_artifacts(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-discovery", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    snapshots_path.write_text(
        json.dumps(
            [
                {
                    "entity_id": ZONE_ID,
                    "entity_type": "zone",
                    "name": ZONE_NAME,
                    "source_id": "src-1",
                    "url": f"https://warcraft.wiki.gg/wiki/{ZONE_WIKI}",
                    "body": "History and geography of the zone.",
                    "section_blocks": [
                        {"section_role": "History", "text": "The zone fell and was reclaimed."},
                        {
                            "section_role": "Instances",
                            "text": f"{INSTANCE_NAME} appears in this zone.",
                        },
                    ],
                    "wiki_links": [
                        f"/wiki/{INSTANCE_NAME.replace(' ', '_')}_(instance)",
                        f"/wiki/{ZONE_WIKI}_storyline",
                        "/wiki/Capital_City",
                    ],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "src-1",
                    "source_class": "warcraft_wiki",
                    "entity_type": "zone",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_discovery_workflow(context, manifest_path)
    for path in outputs.values():
        assert path.exists()


def test_discovery_workflow_detects_instances_and_storylines_without_noisy_links(
    tmp_path: Path,
) -> None:
    context = ensure_run_context("run-test-discovery-signals", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    snapshots_path.write_text(
        json.dumps(
            [
                {
                    "entity_id": ZONE_ID,
                    "entity_type": "zone",
                    "name": ZONE_NAME,
                    "source_id": "src-zone",
                    "url": f"https://warcraft.wiki.gg/wiki/{ZONE_WIKI}",
                    "body": "Zone overview with quests and geography.",
                    "section_blocks": [
                        {"section_role": "Quests", "text": f"See {ZONE_NAME} storyline"},
                        {
                            "section_role": "Geography",
                            "text": f"Contains the dungeon {INSTANCE_NAME}.",
                        },
                    ],
                    "wiki_links": [
                        f"/wiki/{INSTANCE_NAME.replace(' ', '_')}",
                        f"/wiki/File:WorldMap-{ZONE_WIKI}.jpg",
                        f"/wiki/{ZONE_WIKI}?action=edit&section=9",
                    ],
                },
                {
                    "entity_id": INSTANCE_ID,
                    "entity_type": "instance",
                    "name": INSTANCE_NAME,
                    "source_id": "src-instance",
                    "url": f"https://warcraft.wiki.gg/wiki/{INSTANCE_NAME.replace(' ', '_')}",
                    "body": "Instance overview.",
                    "section_blocks": [],
                    "wiki_links": [],
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            [
                {"source_id": "src-zone", "source_class": "warcraft_wiki", "entity_type": "zone"},
                {
                    "source_id": "src-instance",
                    "source_class": "warcraft_wiki",
                    "entity_type": "instance",
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_discovery_workflow(context, manifest_path)

    instance_registry = json.loads(outputs["zone_instance_registry"].read_text(encoding="utf-8"))
    assert any(row["instance_id"] == INSTANCE_ID for row in instance_registry)

    quest_graph = json.loads(outputs["zone_quest_graph"].read_text(encoding="utf-8"))
    assert isinstance(quest_graph, list)

    storyline_targets = json.loads(
        outputs["storyline_traversal_targets"].read_text(encoding="utf-8")
    )
    assert any("storyline" in row.get("source_link", "").lower() for row in storyline_targets)

    candidates = json.loads(outputs["zone_location_candidates"].read_text(encoding="utf-8"))
    candidate_links = {row["source_link"] for row in candidates}
    assert f"/wiki/File:WorldMap-{ZONE_WIKI}.jpg" not in candidate_links
    assert not any("action=edit" in link for link in candidate_links)


def test_discovery_workflow_emits_typed_traversal_targets(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-discovery-typed-targets", artifacts_root=tmp_path / "runs"
    )
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    snapshots_path.write_text(
        json.dumps(
            [
                {
                    "entity_id": ZONE_ID,
                    "entity_type": "zone",
                    "name": ZONE_NAME,
                    "source_id": "src-zone",
                    "url": f"https://warcraft.wiki.gg/wiki/{ZONE_WIKI}",
                    "body": "Zone overview with quests and geography.",
                    "section_blocks": [
                        {"section_role": "Quests", "text": f"See {ZONE_NAME} storyline"},
                        {"section_role": "History", "text": "Crusader and undead conflict"},
                        {
                            "section_role": "Geography",
                            "text": "Brill and Fort City are major locations",
                        },
                    ],
                    "wiki_links": [
                        f"/wiki/{ZONE_WIKI}_storyline",
                        "/wiki/Faction",
                        "/wiki/Example_Faction",
                        "/wiki/Brill",
                        f"/wiki/{INSTANCE_NAME.replace(' ', '_')}",
                    ],
                },
                {
                    "entity_id": INSTANCE_ID,
                    "entity_type": "instance",
                    "name": INSTANCE_NAME,
                    "source_id": "src-instance",
                    "url": f"https://warcraft.wiki.gg/wiki/{INSTANCE_NAME.replace(' ', '_')}",
                    "body": "Instance overview.",
                    "section_blocks": [],
                    "wiki_links": [],
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            [
                {"source_id": "src-zone", "source_class": "warcraft_wiki", "entity_type": "zone"},
                {
                    "source_id": "src-instance",
                    "source_class": "warcraft_wiki",
                    "entity_type": "instance",
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_discovery_workflow(context, manifest_path)

    faction_targets = json.loads(outputs["faction_profile_targets"].read_text(encoding="utf-8"))
    assert any(row["name"] == "Example Faction" for row in faction_targets)

    location_targets = json.loads(outputs["location_profile_targets"].read_text(encoding="utf-8"))
    assert any(row["name"] == "Brill" for row in location_targets)
    assert not any(row["name"] == "Example Faction" for row in location_targets)

    storyline_targets = json.loads(
        outputs["storyline_traversal_targets"].read_text(encoding="utf-8")
    )
    assert any("storyline" in row["title"].lower() for row in storyline_targets)
    assert not any("/wiki/Faction" in row.get("source_link", "") for row in storyline_targets)
    assert all("_storyline" in row.get("source_link", "").lower() for row in storyline_targets)

    instance_profiles = json.loads(outputs["instance_zone_profiles"].read_text(encoding="utf-8"))
    assert any(row["instance_id"] == INSTANCE_ID for row in instance_profiles)

    quest_graph_v3 = json.loads(outputs["zone_quest_graph_v3"].read_text(encoding="utf-8"))
    assert isinstance(quest_graph_v3, list)

    questline_decisions = json.loads(
        outputs["questline_inclusion_decisions"].read_text(encoding="utf-8")
    )
    assert questline_decisions == []


def test_discovery_workflow_types_links_by_section_role_not_keywords(tmp_path: Path) -> None:
    # WS-C: with a structural section role available (structured_links), entity typing
    # must follow the section the link appeared in rather than title keywords. A
    # single-word NPC name in "Notable characters" is a character (excluded from the
    # location pool) even though the keyword path would have mistyped it as a location.
    context = ensure_run_context("run-test-disc-section", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    snapshots_path.write_text(
        json.dumps(
            [
                {
                    "entity_id": ZONE_ID,
                    "entity_type": "zone",
                    "name": ZONE_NAME,
                    "source_id": "src-zone",
                    "url": f"https://warcraft.wiki.gg/wiki/{ZONE_WIKI}",
                    "body": "Zone overview.",
                    "section_blocks": [
                        {"section_role": "Notable characters", "text": "Notable residents."},
                        {"section_role": "Geography", "text": "Major locations."},
                    ],
                    "wiki_links": ["/wiki/Rattlegore", "/wiki/Brill"],
                    "structured_links": [
                        {
                            "href": "/wiki/Rattlegore",
                            "section_role": "Notable characters",
                            "label": "Rattlegore",
                        },
                        {"href": "/wiki/Brill", "section_role": "Geography", "label": "Brill"},
                    ],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            [{"source_id": "src-zone", "source_class": "warcraft_wiki", "entity_type": "zone"}],
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_discovery_workflow(context, manifest_path)

    location_targets = json.loads(outputs["location_profile_targets"].read_text(encoding="utf-8"))
    names = {row["name"] for row in location_targets}
    assert "Brill" in names
    # Single-word NPC routed by section role, not mistyped as a location.
    assert "Rattlegore" not in names


def test_discovery_workflow_hard_rejects_meta_pages_from_maps_section(tmp_path: Path) -> None:
    # WS-C: section-role-first typing admits whole maps/subregions sections, which can include
    # meta-placeholder pages ("Lore location", "Undisplayed location"). These must be hard-rejected
    # by name so they never become location targets/candidates (matches downstream classification).
    context = ensure_run_context("run-test-disc-meta-reject", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    snapshots_path = ingest_dir / "source_snapshots.json"
    manifest_path = ingest_dir / "source_manifest.json"
    snapshots_path.write_text(
        json.dumps(
            [
                {
                    "entity_id": ZONE_ID,
                    "entity_type": "zone",
                    "name": ZONE_NAME,
                    "source_id": "src-zone",
                    "url": f"https://warcraft.wiki.gg/wiki/{ZONE_WIKI}",
                    "body": "Zone overview.",
                    "section_blocks": [
                        {"section_role": "Maps and subregions", "text": "Subregions."}
                    ],
                    "wiki_links": [
                        "/wiki/Felstone_Field",
                        "/wiki/Lore_location",
                        "/wiki/Undisplayed_location",
                    ],
                    "structured_links": [
                        {
                            "href": "/wiki/Felstone_Field",
                            "section_role": "Maps and subregions",
                            "label": "Felstone Field",
                        },
                        {
                            "href": "/wiki/Lore_location",
                            "section_role": "Maps and subregions",
                            "label": "Lore location",
                        },
                        {
                            "href": "/wiki/Undisplayed_location",
                            "section_role": "Maps and subregions",
                            "label": "Undisplayed location",
                        },
                    ],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            [{"source_id": "src-zone", "source_class": "warcraft_wiki", "entity_type": "zone"}],
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_discovery_workflow(context, manifest_path)
    names = {
        row["name"]
        for row in json.loads(outputs["location_profile_targets"].read_text(encoding="utf-8"))
    }
    assert "Felstone Field" in names
    assert "Lore location" not in names
    assert "Undisplayed location" not in names
