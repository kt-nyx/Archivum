from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_run_semantics import SemanticCheckError, _cluster_ids_from_v3, check_run, check_strict_validation


def test_cluster_ids_from_v3_filters_quest_nodes_only() -> None:
    rows = [
        {"zone_id": "zone-a", "node_type": "quest", "cluster_id": "part-1"},
        {"zone_id": "zone-a", "node_type": "cluster", "cluster_id": "part-1-meta"},
    ]
    assert _cluster_ids_from_v3(rows, "zone-a") == {"part-1"}


def _write_minimal_run(run_root: Path, *, draft: dict[str, object]) -> None:
    (run_root / "data" / "drafts" / "zone_page").mkdir(parents=True)
    (run_root / "data" / "discovery").mkdir(parents=True)
    (run_root / "data" / "ingest").mkdir(parents=True)
    (run_root / "data" / "evidence").mkdir(parents=True)
    (run_root / "data" / "glossary").mkdir(parents=True)
    zone_id = "zone-example"
    (run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json").write_text(
        json.dumps(draft, indent=2),
        encoding="utf-8",
    )
    (run_root / "data" / "glossary" / "run_terms.jsonl").write_text(
        json.dumps(
            {
                "term_id": "term-example-zone",
                "label": "Example Zone",
                "wiki_url": "https://example.test/zone",
                "category": "place",
                "aliases": ["example zone"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "data" / "discovery" / "zone_quest_graph_v3.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": zone_id,
                    "node_type": "quest",
                    "cluster_id": "part-1",
                    "title": "Quest A",
                    "source_link": "/wiki/Quest_A",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "data" / "evidence" / "evidence_packs.jsonl").write_text(
        json.dumps(
            {
                "subject_id": zone_id,
                "field_name": "quest_cluster_lore",
                "build_meta": {"subject_zone_id": zone_id, "cluster_id": "part-1"},
                "evidence_items": [{"snippet": "Narrative lore about the front lines."}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _valid_draft() -> dict[str, object]:
    return {
        "zone_id": "zone-example",
        "name": "Example Zone",
        "parent_continent": "eastern-kingdoms",
        "major_questlines": [
            {
                "id": "cluster-part-1",
                "title": "Part 1 - Example Arc",
                "faction": "alliance",
                "cta_hook": "Crusaders push back undead forces along the ruined road.",
                "start_anchor": "Quest A",
                "chain_refs": ["quest-a"],
                "wiki_refs": ["/wiki/Quest_A"],
            }
        ],
        "location_cards": [
            {
                "id": "loc-1",
                "name": "Example Landmark",
                "summary": (
                    "Example Landmark is a fortified outpost in Example Zone where patrols coordinate "
                    "supply lines, defensive operations, and regional scouting missions across the frontier."
                ),
                "decision_reason_codes": ["include"],
            }
        ],
        "at_a_glance": (
            "Once a fertile frontier of the kingdom, the region was devastated during the Third War "
            "and remained blighted for decades before recovery efforts began."
        ),
        "currently": (
            "Crusaders and druids continue to resist undead forces across the ruined frontier "
            "while recovery efforts reshape roads and outposts."
        ),
        "sources": [
            {"source_id": "src-zone", "url": "https://example.test/zone"},
            {"source_id": "src-quest", "url": "https://example.test/quest"},
        ],
        "history_sections": [
            {
                "heading": "The Third War",
                "body": "The region was devastated during the invasion and fell under undead control for decades.",
            }
        ],
    }


def test_check_run_fails_on_unresolved_parent_continent(tmp_path: Path) -> None:
    run_root = tmp_path / "run-parent-continent"
    run_root.mkdir()
    draft = _valid_draft()
    draft["parent_continent"] = "unknown"
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="parent_continent unresolved"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_fails_on_generic_instance_link_summary(tmp_path: Path) -> None:
    run_root = tmp_path / "run-instance-link-stub"
    run_root.mkdir()
    draft = _valid_draft()
    draft["instance_links"] = [
        {
            "id": "instance-example",
            "name": "Example Instance",
            "summary": "Example Instance anchors a key conflict thread linked to this zone.",
            "thumbnail_asset_id": None,
        }
    ]
    draft.setdefault("provenance", {})
    draft["provenance"]["instances"] = {
        "instance-example": [
            {
                "source_id": "src-zone",
                "locator": "section:instances paragraph:1",
                "revision_id": "mw:1",
                "excerpt_hash": "sha256:instance111111111",
            }
        ]
    }
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="generic stub"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_passes_minimal_valid_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run-example"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    check_run(run_root, zone_id="zone-example")


def _schema_valid_zone_page_draft() -> dict[str, object]:
    return {
        "zone_id": "zone-example",
        "name": "Example Zone",
        "wiki_url": "https://example.test/zone",
        "parent_continent": "eastern-kingdoms",
        "expansion_context": "retail",
        "at_a_glance": (
            "Once a fertile frontier of the kingdom, the region was devastated during the Third War "
            "and remained blighted for decades before recovery efforts began."
        ),
        "currently": (
            "Crusaders and druids continue to resist undead forces across the ruined frontier "
            "while recovery efforts reshape roads and outposts."
        ),
        "history_sections": [
            {
                "heading": "The Third War",
                "body": "The region was devastated during the invasion and fell under undead control for decades.",
            }
        ],
        "major_factions": [],
        "major_questlines": [
            {
                "id": "cluster-part-1",
                "title": "Part 1 - Example Arc",
                "faction": "alliance",
                "cta_hook": "Crusaders push back undead forces along the ruined road.",
                "start_anchor": "Quest A",
                "chain_refs": ["quest-a"],
                "include_decision": "include",
                "reason_codes": ["score_based"],
                "wiki_refs": ["/wiki/Quest_A"],
            }
        ],
        "location_cards": [
            {
                "id": "loc-1",
                "name": "Example Landmark",
                "location_type": "major_location",
                "zone_id": "zone-example",
                "wiki_url": "https://example.test/landmark",
                "summary": (
                    "Example Landmark is a fortified outpost in Example Zone where patrols coordinate "
                    "supply lines, defensive operations, and regional scouting missions across the frontier."
                ),
                "significance": "Primary patrol hub for the region.",
                "decision_reason_codes": ["include"],
            }
        ],
        "instance_links": [],
        "glossary_refs": [],
        "sources": [
            {"source_id": "src-zone", "url": "https://example.test/zone"},
            {"source_id": "src-quest", "url": "https://example.test/quest"},
        ],
        "provenance": {
            "at_a_glance": [
                {
                    "source_id": "src-zone",
                    "locator": "section:lead paragraph:1",
                    "revision_id": "mw:1",
                    "excerpt_hash": "sha256:glance111111111",
                }
            ],
            "currently": [
                {
                    "source_id": "src-zone",
                    "locator": "section:quests paragraph:1",
                    "revision_id": "mw:1",
                    "excerpt_hash": "sha256:currently1111",
                }
            ],
            "history": [
                {
                    "source_id": "src-zone",
                    "locator": "section:history paragraph:1",
                    "revision_id": "mw:1",
                    "excerpt_hash": "sha256:history111111",
                }
            ],
            "major_questlines_alliance": {},
            "major_questlines_horde": {},
            "major_questlines_shared": {},
            "major_characters": {},
            "major_factions": {},
            "instances": {},
            "major_landmarks": {},
            "glossary": {},
        },
    }


def test_check_run_strict_fails_when_semantics_pass_but_validate_hard_fails(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run-strict-pointer-cap"
    run_root.mkdir()
    draft = _schema_valid_zone_page_draft()
    draft["provenance"]["at_a_glance"] = [
        {
            "source_id": "src-zone",
            "locator": f"section:lead paragraph:{index}",
            "revision_id": "mw:1",
            "excerpt_hash": f"sha256:cap{index:012d}",
        }
        for index in range(4)
    ]
    _write_minimal_run(run_root, draft=draft)
    check_run(run_root, zone_id="zone-example")
    with pytest.raises(SemanticCheckError, match="provenance.pointer_cap_exceeded"):
        check_strict_validation(run_root)


def test_check_run_fails_when_cluster_card_cap_exceeded(tmp_path: Path) -> None:
    run_root = tmp_path / "run-cap"
    run_root.mkdir()
    draft = _valid_draft()
    draft["major_questlines"] = [
        {
            "id": f"cluster-part-{index}",
            "title": f"Arc {index}",
            "faction": "shared",
            "cta_hook": f"Narrative hook for arc {index} with enough words.",
            "start_anchor": f"Quest {index}",
            "chain_refs": [f"quest-{index}"],
            "wiki_refs": [f"/wiki/Quest_{index}"],
        }
        for index in range(9)
    ]
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="cluster card cap"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_fails_when_hub_resolved_missing_origin(tmp_path: Path) -> None:
    run_root = tmp_path / "run-hub"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    (run_root / "data" / "ingest" / "traversal_report.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "status": "fetched",
                        "role": "quest",
                        "link": "/wiki/Quest_Child",
                        "traversal_origin": "hub_resolved",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with pytest.raises(SemanticCheckError, match="hub_resolved_from"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_validates_cluster_alignment_without_snapshots(tmp_path: Path) -> None:
    run_root = tmp_path / "run-no-snapshots"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    draft = _valid_draft()
    draft["major_questlines"] = [
        {
            "id": "cluster-unknown",
            "title": "Unknown Arc",
            "faction": "shared",
            "cta_hook": "Narrative hook for an unknown cluster with enough words.",
            "start_anchor": "Quest X",
            "chain_refs": ["quest-x"],
            "wiki_refs": ["/wiki/Quest_X"],
        }
    ]
    (run_root / "data" / "drafts" / "zone_page" / "zone-example.json").write_text(
        json.dumps(draft, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(SemanticCheckError, match="unknown cluster ids"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_fails_when_at_a_glance_exceeds_word_cap(tmp_path: Path) -> None:
    run_root = tmp_path / "run-glance"
    run_root.mkdir()
    draft = _valid_draft()
    draft["at_a_glance"] = " ".join(["word"] * 50)
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="at_a_glance"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_warns_on_non_seed_prose_provenance(tmp_path: Path, capsys) -> None:
    run_root = tmp_path / "run-provenance"
    run_root.mkdir()
    draft = _valid_draft()
    draft["provenance"] = {
        "at_a_glance": [{"source_id": "src-aux", "revision_id": "mw:2"}],
        "currently": [{"source_id": "src-zone", "revision_id": "mw:1"}],
        "history": [{"source_id": "src-zone", "revision_id": "mw:1"}],
    }
    _write_minimal_run(run_root, draft=draft)
    (run_root / "data" / "evidence" / "evidence_packs.jsonl").write_text(
        json.dumps(
            {
                "subject_id": "zone-example",
                "field_name": "at_a_glance_input",
                "build_meta": {
                    "subject_zone_id": "zone-example",
                    "source_id": "src-aux",
                    "source_kind": "auxiliary",
                },
                "evidence_items": [{"snippet": "Auxiliary lore snippet."}],
            }
        )
        + "\n"
        + json.dumps(
            {
                "subject_id": "zone-example",
                "field_name": "quest_cluster_lore",
                "build_meta": {
                    "subject_zone_id": "zone-example",
                    "cluster_id": "part-1",
                    "source_id": "src-zone",
                    "source_kind": "seed",
                },
                "evidence_items": [{"snippet": "Narrative lore about the front lines."}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    check_run(run_root, zone_id="zone-example")
    captured = capsys.readouterr()
    assert "WARN: at_a_glance provenance references non-seed source" in captured.out


def test_check_run_fails_when_currently_has_player_meta(tmp_path: Path) -> None:
    run_root = tmp_path / "run-currently"
    run_root.mkdir()
    draft = _valid_draft()
    draft["currently"] = "Players can earn reputation with the faction while exploring the zone."
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="currently"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_fails_when_major_factions_use_generic_filler(tmp_path: Path) -> None:
    run_root = tmp_path / "run-factions"
    run_root.mkdir()
    draft = _valid_draft()
    draft["major_factions"] = [
        {
            "id": "faction-argent-crusade",
            "name": "Argent Crusade",
            "summary": "The Argent Crusade appears in this zone's active conflicts.",
            "wiki_url": "https://warcraft.wiki.gg/wiki/Argent_Crusade",
        }
    ]
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="major_factions"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_fails_when_major_factions_below_minimum_with_candidates(tmp_path: Path) -> None:
    run_root = tmp_path / "run-faction-min"
    run_root.mkdir()
    draft = _valid_draft()
    draft["major_factions"] = []
    _write_minimal_run(run_root, draft=draft)
    (run_root / "data" / "discovery" / "faction_profile_targets.json").write_text(
        json.dumps(
            [
                {"zone_id": "zone-example", "faction_id": "faction-argent-crusade", "name": "Argent Crusade"},
                {"zone_id": "zone-example", "faction_id": "faction-cenarion-circle", "name": "Cenarion Circle"},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    with pytest.raises(SemanticCheckError, match="major_factions count"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_warns_alliance_without_quest_bindings(tmp_path: Path, capsys) -> None:
    run_root = tmp_path / "run-alliance-warn"
    run_root.mkdir()
    draft = _valid_draft()
    draft["major_factions"] = [
        {
            "id": "faction-alliance",
            "name": "Alliance",
            "summary": (
                "Alliance forces coordinate reclamation patrols along the main road in Example Zone while securing "
                "supply lines across the contested frontier throughout the region."
            ),
            "wiki_url": "https://warcraft.wiki.gg/wiki/Alliance",
        }
    ]
    _write_minimal_run(run_root, draft=draft)
    check_run(run_root, zone_id="zone-example")
    captured = capsys.readouterr()
    assert "WARN: 'faction-alliance' present in major_factions without strong conflict signal" in captured.out


def test_check_run_validates_instance_draft(tmp_path: Path, capsys) -> None:
    run_root = tmp_path / "run-instance"
    zone_id = "zone-example"
    instance_id = "instance-archive-vault"
    (run_root / "data" / "drafts" / "zone_page").mkdir(parents=True)
    (run_root / "data" / "drafts" / "instance_page").mkdir(parents=True)
    (run_root / "data" / "discovery").mkdir(parents=True)
    (run_root / "data" / "evidence").mkdir(parents=True)
    (run_root / "data" / "glossary").mkdir(parents=True)
    (run_root / "data" / "glossary" / "run_terms.jsonl").write_text(
        json.dumps(
            {
                "term_id": "term-example-zone",
                "label": "Example Zone",
                "wiki_url": "https://example.test/zone",
                "category": "place",
                "aliases": ["example zone"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    zone_draft = _valid_draft()
    (run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json").write_text(
        json.dumps(zone_draft, indent=2),
        encoding="utf-8",
    )
    overview = " ".join(
        [
            "Archive Vault was founded as a school for battle-mages who studied forbidden necromancy",
            "after the kingdom fell to plague and civil war across the blighted countryside.",
        ]
        * 10
    )
    instance_draft = {
        "instance_id": instance_id,
        "name": "Archive Vault",
        "at_a_glance": (
            "Archive Vault is a blighted academy where necromancers still train recruits beneath haunted halls."
        ),
        "overview": overview,
        "history_sections": [
            {"heading": "Founding", "body": "The vault was built to safeguard forbidden relics after the great war."}
        ],
        "key_enemies": [
            {
                "id": "character-archivist-maelor",
                "name": "Archivist Maelor",
                "summary": (
                    "Archivist Maelor guards the forbidden stacks within Archive Vault, directing hostile "
                    "instructors and preserving grim curricula that threaten nearby settlements."
                ),
            },
            {
                "id": "character-warden-voss",
                "name": "Warden Voss",
                "summary": (
                    "Warden Voss patrols the inner vaults of Archive Vault, enforcing ritual discipline "
                    "among hostile instructors and blocking every attempt to reclaim the academy's secrets."
                ),
            },
        ],
        "sources": [{"source_id": "src-instance", "url": "https://example.test/instance"}],
        "provenance": {
            "identity_header": [{"source_id": "src-instance", "locator": "section:lead paragraph:1"}],
            "story_context": [{"source_id": "src-instance", "locator": "section:history paragraph:1"}],
            "key_characters": {
                "character-archivist-maelor": [
                    {"source_id": "src-instance", "locator": "section:adventurers paragraph:1"}
                ],
                "character-warden-voss": [
                    {"source_id": "src-instance", "locator": "section:adventurers paragraph:2"}
                ],
            },
        },
    }
    (run_root / "data" / "drafts" / "instance_page" / f"{instance_id}.json").write_text(
        json.dumps(instance_draft, indent=2),
        encoding="utf-8",
    )
    (run_root / "data" / "discovery" / "zone_quest_graph_v3.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": zone_id,
                    "node_type": "quest",
                    "cluster_id": "part-1",
                    "title": "Quest A",
                    "source_link": "/wiki/Quest_A",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "data" / "evidence" / "evidence_packs.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "subject_id": zone_id,
                        "field_name": "quest_cluster_lore",
                        "build_meta": {"subject_zone_id": zone_id, "cluster_id": "part-1"},
                        "evidence_items": [{"snippet": "Narrative lore about the front lines."}],
                    }
                ),
                json.dumps(
                    {
                        "subject_id": instance_id,
                        "field_name": "boss_pool",
                        "evidence_items": [{"snippet": "Bosses include /wiki/Archivist_Maelor."}],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    check_run(run_root, zone_id=zone_id)
    captured = capsys.readouterr()
    assert "PASS: instance semantic checks ok" in captured.out


def _write_instance_semantics_run(
    tmp_path: Path,
    *,
    instance_draft: dict[str, object],
    boss_pool_snippet: str = "/wiki/Darkmaster_Gandling",
    section_blocks: list[dict[str, object]] | None = None,
) -> Path:
    run_root = tmp_path / "run-instance-semantics"
    zone_id = "zone-western-plaguelands"
    instance_id = str(instance_draft.get("instance_id", "instance-scholomance"))
    (run_root / "data" / "drafts" / "zone_page").mkdir(parents=True)
    (run_root / "data" / "drafts" / "instance_page").mkdir(parents=True)
    (run_root / "data" / "discovery").mkdir(parents=True)
    (run_root / "data" / "evidence").mkdir(parents=True)
    (run_root / "data" / "ingest").mkdir(parents=True)
    (run_root / "data" / "glossary").mkdir(parents=True)
    zone_draft = _valid_draft()
    zone_draft["zone_id"] = zone_id
    (run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json").write_text(
        json.dumps(zone_draft, indent=2),
        encoding="utf-8",
    )
    (run_root / "data" / "drafts" / "instance_page" / f"{instance_id}.json").write_text(
        json.dumps(instance_draft, indent=2),
        encoding="utf-8",
    )
    (run_root / "data" / "discovery" / "zone_quest_graph_v3.json").write_text("[]", encoding="utf-8")
    (run_root / "data" / "glossary" / "run_terms.jsonl").write_text(
        json.dumps(
            {
                "term_id": "term-example-zone",
                "label": "Example Zone",
                "wiki_url": "https://example.test/zone",
                "category": "place",
                "aliases": ["example zone"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "data" / "evidence" / "evidence_packs.jsonl").write_text(
        json.dumps(
            {
                "subject_id": instance_id,
                "field_name": "boss_pool",
                "build_meta": {"source_id": "src-instance"},
                "evidence_items": [{"snippet": boss_pool_snippet, "section_role": "scholomance_faculty"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if section_blocks is not None:
        (run_root / "data" / "ingest" / "source_snapshots.json").write_text(
            json.dumps(
                [
                    {
                        "entity_id": instance_id,
                        "entity_type": "instance",
                        "section_blocks": section_blocks,
                    }
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
    return run_root


def _minimal_instance_draft(**overrides: object) -> dict[str, object]:
    overview = " ".join(
        [
            "Scholomance was founded as a school for battle-mages who studied forbidden necromancy",
            "after the kingdom fell to plague and civil war across the blighted countryside.",
        ]
        * 10
    )
    draft: dict[str, object] = {
        "instance_id": "instance-scholomance",
        "name": "Scholomance",
        "at_a_glance": "Scholomance is a necromantic academy where hostile faculty still train recruits.",
        "overview": overview,
        "history_sections": [
            {"heading": "Founding", "body": "The academy was built to safeguard forbidden rituals after the great war."}
        ],
        "key_enemies": [],
        "sources": [{"source_id": "src-instance", "url": "https://example.test/scholomance"}],
        "provenance": {
            "identity_header": [{"source_id": "src-instance", "locator": "section:lead paragraph:1"}],
            "story_context": [{"source_id": "src-instance", "locator": "section:history paragraph:1"}],
            "key_characters": {},
        },
    }
    draft.update(overrides)
    return draft


def test_check_run_fails_when_boss_pool_present_but_key_enemies_empty(tmp_path: Path) -> None:
    run_root = _write_instance_semantics_run(tmp_path, instance_draft=_minimal_instance_draft())
    with pytest.raises(SemanticCheckError, match="key_enemies empty despite"):
        check_run(run_root, zone_id="zone-western-plaguelands")


def test_check_run_passes_with_single_key_enemy_when_only_one_boss_name(tmp_path: Path, capsys) -> None:
    draft = _minimal_instance_draft(
        key_enemies=[
            {
                "id": "character-darkmaster-gandling",
                "name": "Darkmaster Gandling",
                "summary": (
                    "Darkmaster Gandling commands Scholomance faculty and anchors the instance's "
                    "necromantic hierarchy within its haunted halls, directing hostile instructors "
                    "and preserving grim curricula."
                ),
            }
        ],
        provenance={
            "identity_header": [{"source_id": "src-instance", "locator": "section:lead paragraph:1"}],
            "story_context": [{"source_id": "src-instance", "locator": "section:history paragraph:1"}],
            "key_characters": {
                "character-darkmaster-gandling": [
                    {"source_id": "src-instance", "locator": "section:scholomance_faculty paragraph:1"}
                ]
            },
        },
    )
    run_root = _write_instance_semantics_run(tmp_path, instance_draft=draft)
    check_run(run_root, zone_id="zone-western-plaguelands")
    captured = capsys.readouterr()
    assert "PASS: instance semantic checks ok" in captured.out


def test_check_run_fails_when_instance_story_context_pointer_cap_exceeded(tmp_path: Path) -> None:
    draft = _minimal_instance_draft(
        key_enemies=[
            {
                "id": "character-darkmaster-gandling",
                "name": "Darkmaster Gandling",
                "summary": (
                    "Darkmaster Gandling commands Scholomance faculty and anchors the instance's "
                    "necromantic hierarchy within its haunted halls, directing hostile instructors "
                    "and preserving grim curricula."
                ),
            }
        ],
        provenance={
            "identity_header": [{"source_id": "src-instance", "locator": "section:lead paragraph:1"}],
            "story_context": [
                {"source_id": "src-instance", "locator": f"section:history paragraph:{index}"}
                for index in range(1, 5)
            ],
            "key_characters": {
                "character-darkmaster-gandling": [
                    {"source_id": "src-instance", "locator": "section:scholomance_faculty paragraph:1"}
                ]
            },
        },
    )
    run_root = _write_instance_semantics_run(tmp_path, instance_draft=draft)
    with pytest.raises(SemanticCheckError, match="story_context provenance exceeds cap"):
        check_run(run_root, zone_id="zone-western-plaguelands")


def test_check_run_fails_when_instance_identity_header_pointer_cap_exceeded(tmp_path: Path) -> None:
    draft = _minimal_instance_draft(
        key_enemies=[
            {
                "id": "character-darkmaster-gandling",
                "name": "Darkmaster Gandling",
                "summary": (
                    "Darkmaster Gandling commands Scholomance faculty and anchors the instance's "
                    "necromantic hierarchy within its haunted halls, directing hostile instructors "
                    "and preserving grim curricula."
                ),
            }
        ],
        provenance={
            "identity_header": [
                {"source_id": "src-instance", "locator": f"section:lead paragraph:{index}"}
                for index in range(1, 5)
            ],
            "story_context": [{"source_id": "src-instance", "locator": "section:history paragraph:1"}],
            "key_characters": {
                "character-darkmaster-gandling": [
                    {"source_id": "src-instance", "locator": "section:scholomance_faculty paragraph:1"}
                ]
            },
        },
    )
    run_root = _write_instance_semantics_run(tmp_path, instance_draft=draft)
    with pytest.raises(SemanticCheckError, match="identity_header provenance exceeds cap"):
        check_run(run_root, zone_id="zone-western-plaguelands")


def test_check_run_fails_when_two_boss_candidates_but_one_key_enemy(tmp_path: Path) -> None:
    draft = _minimal_instance_draft(
        key_enemies=[
            {
                "id": "character-darkmaster-gandling",
                "name": "Darkmaster Gandling",
                "summary": (
                    "Darkmaster Gandling commands Scholomance faculty and anchors the instance's "
                    "necromantic hierarchy within its haunted halls, directing hostile instructors "
                    "and preserving grim curricula."
                ),
            }
        ],
        provenance={
            "identity_header": [{"source_id": "src-instance", "locator": "section:lead paragraph:1"}],
            "story_context": [{"source_id": "src-instance", "locator": "section:history paragraph:1"}],
            "key_characters": {
                "character-darkmaster-gandling": [
                    {"source_id": "src-instance", "locator": "section:scholomance_faculty paragraph:1"}
                ]
            },
        },
    )
    run_root = _write_instance_semantics_run(
        tmp_path,
        instance_draft=draft,
        boss_pool_snippet=(
            "Bosses include /wiki/Darkmaster_Gandling and /wiki/Jandice_Barov within Scholomance."
        ),
        section_blocks=[
            {
                "section_role": "adventurers",
                "text": "Bosses include /wiki/Darkmaster_Gandling and /wiki/Jandice_Barov.",
            }
        ],
    )
    with pytest.raises(SemanticCheckError, match="below minimum 2"):
        check_run(run_root, zone_id="zone-western-plaguelands")


def test_check_run_validates_linked_glossary_refs(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("LORE_GLOSSARY_MIN_TERMS", "2")
    run_root = tmp_path / "run-glossary"
    _write_minimal_run(run_root, draft=_valid_draft())
    draft_path = run_root / "data" / "drafts" / "zone_page" / "zone-example.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["glossary_refs"] = [
        {
            "term_id": "term-example-zone",
            "label": "Example Zone",
            "wiki_url": "https://example.test/zone",
        },
        {
            "term_id": "term-scourge",
            "label": "Scourge",
            "wiki_url": "https://example.test/scourge",
        },
    ]
    draft.setdefault("provenance", {})
    draft["provenance"]["glossary"] = {
        "term-example-zone": [
            {
                "source_id": "src-zone",
                "locator": "section:lead paragraph:1",
                "revision_id": "mw:1",
                "excerpt_hash": "sha256:glossary111111111",
            }
        ],
        "term-scourge": [
            {
                "source_id": "src-zone",
                "locator": "section:history paragraph:1",
                "revision_id": "mw:1",
                "excerpt_hash": "sha256:glossary222222222",
            }
        ],
    }
    draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    glossary_path = run_root / "data" / "glossary" / "run_terms.jsonl"
    glossary_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "term_id": "term-example-zone",
                        "label": "Example Zone",
                        "wiki_url": "https://example.test/zone",
                        "category": "place",
                        "aliases": ["example zone"],
                    }
                ),
                json.dumps(
                    {
                        "term_id": "term-scourge",
                        "label": "Scourge",
                        "wiki_url": "https://example.test/scourge",
                        "category": "faction",
                        "aliases": ["scourge"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    check_run(run_root, zone_id="zone-example")
    captured = capsys.readouterr()
    assert "PASS: glossary semantic checks ok" in captured.out


def test_check_run_fails_when_run_terms_missing(tmp_path: Path) -> None:
    run_root = tmp_path / "run-no-glossary-terms"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    (run_root / "data" / "glossary" / "run_terms.jsonl").unlink()
    with pytest.raises(SemanticCheckError, match="missing run-scoped glossary terms file"):
        check_run(run_root, zone_id="zone-example")


