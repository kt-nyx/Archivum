from __future__ import annotations

import json
from pathlib import Path

from pipeline.common.run_context import ensure_run_context
from pipeline.discovery.workflow import (
    _collapse_location_variants,
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


def _loc(name: str, role: str = "maps_subregions", zone: str = "z") -> dict[str, object]:
    slug = name.lower().replace("'", "").replace(" ", "-")
    return {
        "zone_id": zone,
        "location_id": f"location-{slug}",
        "name": name,
        "source_section_role": role,
    }


def test_collapse_variants_folds_descriptor_names_into_base() -> None:
    cands = [
        _loc("Andorhal", role="history"),
        _loc("Ruins of Andorhal"),
        _loc("Hearthglen", role="other"),
        _loc("Hearthglen Hills"),
        _loc("Hearthglen Woods"),
        _loc("Sorrow Hill"),
        _loc("Sorrow Hill Crypt"),
        _loc("Caer Darrow"),
        _loc("Isle of Darrow"),
    ]
    kept, _roles = _collapse_location_variants(cands)
    names = {c["name"] for c in kept}
    assert "Andorhal" in names and "Ruins of Andorhal" not in names
    assert "Hearthglen" in names and "Hearthglen Hills" not in names and "Hearthglen Woods" not in names
    assert "Sorrow Hill" in names and "Sorrow Hill Crypt" not in names
    # Distinct places (not a token-subsequence of one another) survive.
    assert "Caer Darrow" in names and "Isle of Darrow" in names


def test_collapse_variants_upgrades_base_role_to_strongest_in_group() -> None:
    # Hearthglen is mentioned in "other" prose but its map-listed sub-features carry
    # maps_subregions; the surviving base inherits the strongest role so it is not stranded.
    cands = [_loc("Hearthglen", role="other"), _loc("Hearthglen Pass", role="maps_subregions")]
    kept, roles = _collapse_location_variants(cands)
    base = next(c for c in kept if c["name"] == "Hearthglen")
    assert base["source_section_role"] == "maps_subregions"
    assert roles[str(base["location_id"])] == "maps_subregions"


def test_collapse_variants_keeps_same_owner_distinct_places() -> None:
    # "Dalson's Tears" and "Dalson's Farm" share an owner but neither is a subsequence of the
    # other, so the conservative rule leaves both.
    cands = [_loc("Dalson's Tears"), _loc("Dalson's Farm")]
    kept, _roles = _collapse_location_variants(cands)
    assert {c["name"] for c in kept} == {"Dalson's Tears", "Dalson's Farm"}


def test_discovery_workflow_extracts_marquee_landmarks_from_mixed_sections(tmp_path: Path) -> None:
    # Caer Darrow is linked under "lead" first but also under maps/subregions; role resolution must
    # prefer the location-bearing section so the 2-token NPC heuristic does not wrongly drop it.
    # Uther's Tomb is linked only under "other" but its place token (tomb) types it as a location.
    context = ensure_run_context("run-test-disc-marquee", artifacts_root=tmp_path / "runs")
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
                        {"section_role": "Lead", "text": "Caer Darrow sits on the lake."},
                        {"section_role": "Maps and subregions", "text": "Caer Darrow; Sorrow Hill."},
                        {"section_role": "History", "text": "Uther's Tomb stands above the lake."},
                    ],
                    "wiki_links": ["/wiki/Caer_Darrow", "/wiki/Uther%27s_Tomb", "/wiki/Sorrow_Hill"],
                    "structured_links": [
                        {"href": "/wiki/Caer_Darrow", "section_role": "Lead", "label": "Caer Darrow"},
                        {
                            "href": "/wiki/Caer_Darrow",
                            "section_role": "Maps and subregions",
                            "label": "Caer Darrow",
                        },
                        {
                            "href": "/wiki/Uther%27s_Tomb",
                            "section_role": "History",
                            "label": "Uther's Tomb",
                        },
                        {
                            "href": "/wiki/Sorrow_Hill",
                            "section_role": "Maps and subregions",
                            "label": "Sorrow Hill",
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
    assert "Caer Darrow" in names
    assert "Uther's Tomb" in names

    # Lore-significance: a place named in the history narrative is a marquee landmark; a maps-only
    # entry (Sorrow Hill, listed only under "Maps and subregions") is gameplay chrome.
    candidates = {
        row["name"]: row
        for row in json.loads(outputs["zone_location_candidates"].read_text(encoding="utf-8"))
    }
    assert candidates["Caer Darrow"]["lore_significant"] is True
    assert candidates["Uther's Tomb"]["lore_significant"] is True
    assert candidates["Sorrow Hill"]["lore_significant"] is False


def test_discovery_workflow_excludes_cast_named_in_history_and_characters(tmp_path: Path) -> None:
    # A character linked in BOTH the history prose and the notable-characters roster had its
    # inferred section role resolve to "history", slipping past section-role typing into the
    # location pool (Thassarian). The notable-characters roster is an authoritative cast denylist;
    # such a name must never become a location. Ner'zhul (apostrophe-infix NPC in a non-geography
    # section) is rejected by the name heuristic.
    context = ensure_run_context("run-test-disc-cast", artifacts_root=tmp_path / "runs")
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
                        {"section_role": "History", "text": "Thassarian and Ner'zhul fought here."},
                        {"section_role": "Notable characters", "text": "Cast."},
                        {"section_role": "Maps and subregions", "text": "Subregions."},
                    ],
                    "wiki_links": [
                        "/wiki/Thassarian",
                        "/wiki/Ner%27zhul",
                        "/wiki/Caer_Darrow",
                    ],
                    "structured_links": [
                        # Thassarian appears in history first, but is rostered as a character.
                        {
                            "href": "/wiki/Thassarian",
                            "section_role": "History",
                            "label": "Thassarian",
                        },
                        {
                            "href": "/wiki/Thassarian",
                            "section_role": "Notable characters",
                            "label": "Thassarian",
                        },
                        {
                            "href": "/wiki/Ner%27zhul",
                            "section_role": "History",
                            "label": "Ner'zhul",
                        },
                        {
                            "href": "/wiki/Caer_Darrow",
                            "section_role": "Maps and subregions",
                            "label": "Caer Darrow",
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
    assert "Caer Darrow" in names  # a real maps-section landmark survives
    assert "Thassarian" not in names  # rostered cast member
    assert "Ner'zhul" not in names  # apostrophe-infix NPC

    # Slice D: the rostered cast member is not dropped — it becomes a character profile crawl target.
    character_targets = json.loads(
        outputs["character_profile_targets"].read_text(encoding="utf-8")
    )
    character_names = {row["name"] for row in character_targets}
    assert "Thassarian" in character_names
    assert "Caer Darrow" not in character_names  # a place never becomes a character target
    thassarian = next(row for row in character_targets if row["name"] == "Thassarian")
    assert thassarian["character_id"] == "character-thassarian"
    assert thassarian["source_link"]
