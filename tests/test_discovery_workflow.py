from __future__ import annotations

import json
from pathlib import Path

from pipeline.common.run_context import ensure_run_context
from pipeline.discovery.workflow import (
    _collapse_location_variants,
    _collect_instance_character_targets,
    _collect_zone_faction_targets,
    _effective_section_slug,
    _section_role,
    run_discovery_workflow,
)
from tests.factories.snapshots import with_required_snapshot_schema

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
            with_required_snapshot_schema([
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
            ]),
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
            with_required_snapshot_schema([
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
            ]),
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
            with_required_snapshot_schema([
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
                            "section_role": "History",
                            "text": "Crusader and undead conflict",
                            # Slice 13: faction targets come from block links resolved
                            # against the org registry, never from name-shape typing.
                            "links": [
                                {"anchor_text": "Argent Crusade", "href": "/wiki/Argent_Crusade"}
                            ],
                        },
                        {
                            "section_role": "Geography",
                            "text": "Brill and Fort City are major locations",
                        },
                    ],
                    "wiki_links": [
                        f"/wiki/{ZONE_WIKI}_storyline",
                        "/wiki/Faction",
                        "/wiki/Argent_Crusade",
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
            ]),
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
    assert any(row["name"] == "Argent Crusade" for row in faction_targets)
    assert all(row["faction_id"] for row in faction_targets)

    location_targets = json.loads(outputs["location_profile_targets"].read_text(encoding="utf-8"))
    assert any(row["name"] == "Brill" for row in location_targets)
    assert not any(row["name"] == "Argent Crusade" for row in location_targets)

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


def _org_link_block(section_role: str, *hrefs: str, parent: str = "") -> dict[str, object]:
    block: dict[str, object] = {
        "section_role": section_role,
        "text": "Narrative prose naming the linked groups.",
        "links": [{"anchor_text": href.rsplit("/", 1)[-1].replace("_", " "), "href": href} for href in hrefs],
    }
    if parent:
        block["parent_section_role"] = parent
    return block


def test_zone_faction_targets_rank_registry_orgs_by_link_frequency_and_section() -> None:
    """Slice 13: targets are org-registry links from the seed page, ranked by
    link frequency x section class — history/quest links outrank chrome, RPG contributes
    nothing, and non-organization links never become targets."""
    blocks = [
        _org_link_block("history_edit", "/wiki/Argent_Crusade", "/wiki/Cenarion_Circle"),
        _org_link_block("the_scourging_edit", "/wiki/Argent_Crusade", parent="history_edit"),
        # Questline-bound org: linked from the quests/storyline section.
        _org_link_block("quests_edit", "/wiki/Alliance"),
        # Kirin Tor appears once in an unclassified section: weakest, but still targeted.
        _org_link_block("trivia_edit", "/wiki/Kirin_Tor"),
        # RPG-only links never become targets.
        _org_link_block("in_the_rpg_organizations", "/wiki/Scarlet_Crusade"),
        # Non-organization links (places) never become faction targets.
        _org_link_block("history_edit", "/wiki/Andorhal"),
    ]
    targets = _collect_zone_faction_targets("zone-example", "Example Zone", blocks)
    names = [row["name"] for row in targets]
    assert names[0] == "Argent Crusade"  # two history-class links
    assert "Cenarion Circle" in names
    assert "Alliance" in names  # questline-bound org is targeted
    assert "Kirin Tor" in names
    assert "Scarlet Crusade" not in names
    assert "Andorhal" not in names
    argent = next(row for row in targets if row["name"] == "Argent Crusade")
    assert argent["faction_id"] == "faction-argent-crusade"
    assert argent["source_link"] == "/wiki/Argent_Crusade"
    assert argent["source_section_role"] == "history"


def test_zone_faction_targets_resolve_identity_from_link_target_not_anchor_text() -> None:
    # A prose anchor ("the necromancers' cult") targets the canonical article; the
    # registry title is the identity, so anchor wording can never mint a faction name.
    blocks = [
        {
            "section_role": "history_edit",
            "text": "The necromancers' cult ruled beneath the lake.",
            "links": [
                {"anchor_text": "the necromancers' cult", "href": "/wiki/Cult_of_the_Damned"}
            ],
        }
    ]
    targets = _collect_zone_faction_targets("zone-example", "Example Zone", blocks)
    assert [row["name"] for row in targets] == ["Cult of the Damned"]


def test_zone_faction_targets_capped() -> None:
    orgs = [
        "/wiki/Argent_Crusade",
        "/wiki/Cenarion_Circle",
        "/wiki/Alliance",
        "/wiki/Horde",
        "/wiki/Forsaken",
        "/wiki/Kirin_Tor",
        "/wiki/Scarlet_Crusade",
        "/wiki/Argent_Dawn",
        "/wiki/Cult_of_the_Damned",
        "/wiki/Scourge",
        "/wiki/Earthen_Ring",
        "/wiki/Cenarion_Expedition",
    ]
    blocks = [_org_link_block("history_edit", href) for href in orgs]
    targets = _collect_zone_faction_targets("zone-example", "Example Zone", blocks)
    assert len(targets) == 10


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
            with_required_snapshot_schema([
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
            ]),
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
            with_required_snapshot_schema([
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
            ]),
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
            with_required_snapshot_schema([
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
            ]),
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


def test_collect_instance_character_targets_takes_roster_not_places() -> None:
    # Slice D: instance character targets come from the boss-roster structured links, scoped to the
    # instance. Places (Caer Darrow), denizen trash (Risen Guard), and meta props (Chamber of
    # Summoning) are filtered; the curated boss roster survives.
    snapshots = [
        {
            "entity_id": "instance-scholomance",
            "entity_type": "instance",
            "name": "Scholomance",
            "structured_links": [
                {"label": "Darkmaster Gandling", "href": "/wiki/Darkmaster_Gandling",
                 "section_role": "scholomance_faculty_edit"},
                {"label": "Lilian Voss", "href": "/wiki/Lilian_Voss",
                 "section_role": "scholomance_faculty_edit"},
                {"label": "Rattlegore", "href": "/wiki/Rattlegore",
                 "section_role": "dungeon_scholomance_edit"},
                # A place linked from the adventure-guide section is rejected.
                {"label": "Caer Darrow", "href": "/wiki/Caer_Darrow",
                 "section_role": "adventure_guide_edit"},
                # Denizen-section trash is excluded wholesale.
                {"label": "Risen Guard", "href": "/wiki/Risen_Guard",
                 "section_role": "dungeon_denizens_edit"},
                # A non-roster (loot) section is ignored.
                {"label": "Spectral Necklace", "href": "/wiki/Spectral_Necklace",
                 "section_role": "loot_edit"},
            ],
        },
        # A zone seed contributes no character targets.
        {
            "entity_id": "zone-western-plaguelands",
            "entity_type": "zone",
            "name": "Western Plaguelands",
            "structured_links": [
                {"label": "Tirion Fordring", "href": "/wiki/Tirion_Fordring",
                 "section_role": "notable_characters"},
            ],
        },
    ]
    targets = _collect_instance_character_targets(snapshots)
    names = {t["name"] for t in targets}
    assert names == {"Darkmaster Gandling", "Lilian Voss", "Rattlegore"}
    assert all(t["zone_id"] == "instance-scholomance" for t in targets)
    assert all(t["character_id"].startswith("character-") for t in targets)


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
            with_required_snapshot_schema([
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
            ]),
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

    # Slice D: zone-page characters are NOT crawled — only instance rosters are (zones emit no
    # key-character cards). So a zone notable like Thassarian produces no character profile target.
    character_targets = json.loads(
        outputs["character_profile_targets"].read_text(encoding="utf-8")
    )
    assert character_targets == []
