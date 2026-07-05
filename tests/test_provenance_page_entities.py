from __future__ import annotations

from pipeline.generate.draft.pages import build_zone_page
from pipeline.generate.draft.provenance import build_revision_index, collect_sources_manifest
from tests.factories.wiki_first_pages import (
    minimal_instance_page_payload,
    minimal_zone_page_payload,
)
from tests.test_validation_engine import validate_payload


def test_build_revision_index_merges_fact_pack_and_snapshots() -> None:
    fact_pack = {
        "source_ids": ["src-zone"],
        "revision_ids": ["mw:1"],
        "source_urls": {"src-zone": "https://example.test/zone"},
    }
    snapshots = [
        {
            "source_id": "src-quest-a",
            "revision_id": "mw:99",
            "url": "https://example.test/quest-a",
        },
        {
            "source_id": "src-zone",
            "revision_id": "mw:2",
            "url": "https://example.test/zone-v2",
        },
    ]
    revision_map, source_urls = build_revision_index(fact_pack, snapshots)
    assert revision_map["src-zone"] == "mw:2"
    assert revision_map["src-quest-a"] == "mw:99"
    assert source_urls["src-zone"] == "https://example.test/zone-v2"
    assert source_urls["src-quest-a"] == "https://example.test/quest-a"


def test_collect_sources_manifest_includes_history_and_card_pointers() -> None:
    payload = minimal_zone_page_payload()
    payload["provenance"]["major_questlines_alliance"] = {
        "cluster-part-1": [
            {
                "source_id": "src-quest-a",
                "locator": "section:description paragraph:1",
                "revision_id": "mw:9",
                "excerpt_hash": "sha256:questaaaaaaaaaaaa",
            }
        ]
    }
    payload["history_sections"][0]["source_refs"] = [
        {
            "source_id": "src-zone",
            "locator": "section:history paragraph:1",
            "revision_id": "mw:42",
            "excerpt_hash": "sha256:history1111111111",
        }
    ]
    sources = collect_sources_manifest(
        payload,
        {"src-zone": "mw:42", "src-quest-a": "mw:9"},
        {
            "src-zone": "https://example.test/zone",
            "src-quest-a": "https://example.test/quest-a",
        },
    )
    source_ids = {row["source_id"] for row in sources}
    assert source_ids == {"src-quest-a", "src-zone"}


def test_build_zone_page_uses_snapshot_revision_for_quest_provenance(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    questline_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-1",
            "cluster_title": "Part 1 - Example Arc",
            "cluster_order": 1,
            "order_in_cluster": 1,
            "node_id": "quest-a",
            "title": "Quest A",
            "faction_binding": "alliance",
            "source_link": "/wiki/Quest_A",
        }
    ]
    evidence_rows = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Example_Zone",
                    "source_title": "Example Zone",
                    "snippet": "The zone is a war-ravaged frontier where patrols secure the reclaimed key routes.",
                    "section_role": "lead",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Example_Zone",
                    "source_title": "Example Zone",
                    "snippet": "Patrols continue to secure roads while hostile forces pressure nearby settlements.",
                    "section_role": "quests",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Example_Zone",
                    "source_title": "Example Zone",
                    "snippet": (
                        "The region was devastated during the invasion and fell under undead control "
                        "for decades before military campaigns began restoring order across the frontier, "
                        "broken keeps, and scattered villages throughout the zone."
                    ),
                    "section_role": "history",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "quest_cluster_lore",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Quest_A",
                    "source_title": "Quest A",
                    "snippet": "Crusaders push back undead forces along the ruined road.",
                    "section_role": "description",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {
                "source_id": "src-quest-a",
                "cluster_id": "part-1",
                "subject_zone_id": zone_id,
            },
        },
    ]
    snapshots = [
        {
            "source_id": "src-zone",
            "revision_id": "mw:1",
            "url": "https://warcraft.wiki.gg/wiki/Example_Zone",
        },
        {
            "source_id": "src-quest-a",
            "revision_id": "mw:quest",
            "url": "https://warcraft.wiki.gg/wiki/Quest_A",
        },
    ]
    draft = build_zone_page(
        {
            "entity_id": zone_id,
            "name": "Example Zone",
            "source_ids": ["src-zone"],
            "revision_ids": ["mw:1"],
            "source_urls": {"src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone"},
        },
        evidence_rows,
        questline_rows,
        [],
        [],
        {},
        {},
        {"final_decision": "include"},
        snapshots=snapshots,
    )
    assert draft["provenance"]["at_a_glance"]
    assert draft["provenance"]["currently"]
    assert draft["history_sections"][0]["source_refs"]
    card_id = draft["major_questlines"][0]["id"]
    assert draft["provenance"]["major_questlines_alliance"][card_id]
    assert (
        draft["provenance"]["major_questlines_alliance"][card_id][0]["source_id"] == "src-quest-a"
    )
    source_ids = {row["source_id"] for row in draft["sources"]}
    assert "src-quest-a" in source_ids


def test_build_zone_page_history_provenance_falls_back_when_used_ids_empty(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence_rows = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": "The zone is a war-ravaged frontier where patrols secure the reclaimed key routes.",
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "snippet": "Patrols continue to secure roads while hostile forces pressure nearby settlements.",
                    "section_role": "quests",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "snippet": (
                        "The region was devastated during the invasion and fell under undead control "
                        "for decades before military campaigns began restoring order across the frontier, "
                        "broken keeps, and scattered villages throughout the zone."
                    ),
                    "section_role": "history",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
    ]
    draft = build_zone_page(
        {
            "entity_id": zone_id,
            "name": "Example Zone",
            "source_ids": ["src-zone"],
            "revision_ids": ["mw:1"],
            "source_urls": {"src-zone": "https://example.test/zone"},
        },
        evidence_rows,
        [],
        [],
        [],
        {},
        {},
        None,
    )
    assert draft["history_sections"][0]["source_refs"]
    assert draft["provenance"]["history"]


def test_zone_page_major_factions_provenance_required() -> None:
    payload = minimal_zone_page_payload()
    payload["major_factions"] = [
        {
            "id": "faction-argent-crusade",
            "name": "Argent Crusade",
            "wiki_url": "https://example.test/argent-crusade",
            "summary": (
                "The Argent Crusade maintains patrol routes and defensive operations across "
                "Testlands while coordinating supply lines and regional scouting missions."
            ),
        }
    ]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "provenance.missing_card_pointers" and "major_factions" in issue.path
        for issue in report.issues
    )


def test_zone_page_glossary_provenance_required_when_refs_present() -> None:
    payload = minimal_zone_page_payload()
    payload["glossary_refs"] = [
        {
            "term_id": "term-testlands",
            "label": "Testlands",
            "wiki_url": "https://example.test/testlands",
        }
    ]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "provenance.missing_card_pointers" and "glossary" in issue.path
        for issue in report.issues
    )


def test_instance_page_major_factions_provenance_required() -> None:
    payload = minimal_instance_page_payload()
    payload["major_factions"] = [
        {
            "id": "faction-scourge",
            "name": "Scourge",
            "wiki_url": "https://example.test/scourge",
            "summary": (
                "The Scourge maintains ritual pressure across Test Dungeon while coordinating "
                "recruitment, battlefield reinforcement, and patrol disruption beyond its gates."
            ),
        }
    ]
    report = validate_payload("instance_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "provenance.missing_card_pointers" and "major_factions" in issue.path
        for issue in report.issues
    )


def test_linker_writes_glossary_provenance_for_zone_page(tmp_path, monkeypatch) -> None:
    from pipeline.common.run_context import ensure_run_context
    from pipeline.linker.linker import run_glossary_linker

    context = ensure_run_context("run-test-page-glossary", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-testlands.json"
    payload = minimal_zone_page_payload()
    draft_path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda _context=None: [
            {
                "term_id": "term-testlands",
                "alias": "Testlands",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "place",
            }
        ],
    )
    monkeypatch.setattr(
        "pipeline.linker.linker._load_term_metadata",
        lambda _context=None: {
            "term-testlands": {
                "term_id": "term-testlands",
                "label": "Testlands",
                "wiki_url": "https://example.test/testlands",
                "category": "place",
            }
        },
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    draft = __import__("json").loads(draft_path.read_text(encoding="utf-8"))
    assert draft["glossary_refs"]
    assert draft["provenance"]["glossary"]["term-testlands"]
