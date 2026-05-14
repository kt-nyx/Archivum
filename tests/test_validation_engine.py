import json
from pathlib import Path
from typing import Any, cast

from pipeline.validate.engine import validate_payload

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(*parts: str) -> dict[str, Any]:
    fixture_path = FIXTURES_DIR.joinpath(*parts)
    return cast(dict[str, Any], json.loads(fixture_path.read_text(encoding="utf-8")))


def _valid_instance_payload() -> dict[str, Any]:
    return {
        "id": "instance-test-watchfort",
        "slug": "test-watchfort",
        "name": "Test Watchfort",
        "type": "dungeon",
        "zone_id": "zone-test-westfall",
        "identity_header": (
            "Command bastion used for tactical planning and emergency response coordination."
        ),
        "story_context": (
            "The fort's story context explains how commanders coordinated layered defenses, "
            "secured logistics corridors, and stabilized nearby settlements during repeated "
            "incursions. It highlights shifting alliances, supply strain, and the relationship "
            "between local patrol leadership and broader strategic directives. The narrative also "
            "covers why players engage this location now, including unresolved threats, contested "
            "routes, and command decisions that continue to shape regional outcomes. Additional "
            "accounts describe how weather disruptions, damaged bridges, and unreliable signal "
            "relays complicated every deployment window, forcing leaders to stage backup patrol "
            "chains and contingency escorts. Archival records also document rotating priorities "
            "between civilian evacuation, supply escort duty, perimeter reinforcement, and rapid "
            "counter-strike operations, showing why the site remained strategically relevant "
            "long after the initial crisis phase appeared contained. Command diaries further "
            "emphasize leadership turnover, equipment shortfalls, and recurring communication "
            "delays that forced tactical improvisation under pressure. Taken together, these "
            "events explain both the fort's narrative significance and the player's present "
            "objective to secure operational continuity before adjacent regions "
            "rapidly destabilize, "
            "escalation markers spike, and fallback routes collapse."
        ),
        "key_characters": [
            {
                "id": "character-test-captain",
                "name": "Captain Rell",
                "summary": (
                    "Fort commander managing escalation control, patrol priorities, "
                    "and civilian risk mitigation."
                ),
            },
            {
                "id": "character-test-scout",
                "name": "Scout Ven",
                "summary": (
                    "Recon specialist coordinating route intelligence and rapid "
                    "response handoffs under pressure."
                ),
            },
        ],
        "zone_backlink": {
            "zone_id": "zone-test-westfall",
            "label": "Back to Test Westfall",
        },
        "glossary": [{"term_id": "term-test"}],
        "sources": [
            {
                "source_id": "src-primary",
                "url": "https://example.test/source/primary",
                "revision_id": "rev-2",
            }
        ],
        "provenance": {
            "identity_header": [
                {
                    "source_id": "src-primary",
                    "locator": "section:identity paragraph:1",
                    "revision_id": "rev-2",
                    "excerpt_hash": "sha256:aaaa1111",
                }
            ],
            "story_context": [
                {
                    "source_id": "src-primary",
                    "locator": "section:story paragraph:1",
                    "revision_id": "rev-2",
                    "excerpt_hash": "sha256:bbbb2222",
                },
                {
                    "source_id": "src-primary",
                    "locator": "section:story paragraph:2",
                    "revision_id": "rev-2",
                    "excerpt_hash": "sha256:cccc3333",
                },
            ],
            "key_characters": {
                "character-test-captain": [
                    {
                        "source_id": "src-primary",
                        "locator": "section:characters paragraph:1",
                        "revision_id": "rev-2",
                        "excerpt_hash": "sha256:dddd4444",
                    }
                ],
                "character-test-scout": [
                    {
                        "source_id": "src-primary",
                        "locator": "section:characters paragraph:2",
                        "revision_id": "rev-2",
                        "excerpt_hash": "sha256:eeee5555",
                    }
                ],
            },
        },
        "expansion": "test-era",
        "wing_count": 1,
        "version_notes": "Validation fixture for warning coverage.",
        "related_factions": ["faction-test"],
        "media_assets": [],
    }


def _valid_asset_payload() -> dict[str, Any]:
    return {
        "id": "asset-hearthglen-banner",
        "asset_type": "image",
        "title": (
            "Hearthglen ridge panorama retained for Argent Crusade staging imagery "
            "in pilot UI banners."
        ),
        "source_url": "https://example.test/asset/hearthglen-banner.png",
        "license": "CC-BY-SA-4.0",
        "credit": "Example Photographer Collective",
        "allowed_use": True,
        "allowed_use_reason": (
            "Creative Commons license permits redistribution with attribution "
            "for non-commercial addon previews and documentation screenshots."
        ),
        "proof_ref": "proof:third-party/hearthglen-banner-license-bundle",
        "associated_entity_ids": ["zone-western-plaguelands"],
        "sources": [
            {
                "source_id": "src-license-bundle",
                "url": "https://example.test/legal/hearthglen-license-bundle",
                "revision_id": "bundle-v3",
            }
        ],
        "caption": (
            "Wide ridge vista emphasizing reclaimed foothills and patrol corridors "
            "without revealing spoiler-heavy beats beyond Western Plaguelands tone."
        ),
        "provenance": {
            "caption": [
                {
                    "source_id": "src-license-bundle",
                    "locator": "bundle:caption paragraph:1",
                    "revision_id": "bundle-v3",
                    "excerpt_hash": "sha256:assetcaption1111",
                }
            ],
            "metadata": [
                {
                    "source_id": "src-license-bundle",
                    "locator": "bundle:metadata paragraph:1",
                    "revision_id": "bundle-v3",
                    "excerpt_hash": "sha256:assetmeta222222",
                }
            ],
        },
    }


def _valid_sub_zone_payload() -> dict[str, Any]:
    return {
        "id": "subzone-andorhal",
        "slug": "andorhal",
        "name": "Andorhal",
        "parent_zone_id": "zone-western-plaguelands",
        "at_a_glance": "Former grain city now central to post-war territorial conflict.",
        "currently": (
            "Andorhal remains a hardened conflict site where patrol discipline and defensive "
            "readiness are required to keep nearby routes operational."
        ),
        "history": (
            "Once a Lordaeron logistics center, the city fell during plague-era devastation and "
            "became a recurring military objective through later faction campaigns."
        ),
        "major_questlines_alliance": [
            {
                "id": "ql-andorhal-alliance-subzone",
                "faction": "alliance",
                "title": "Alliance Frontline Push",
                "hook": (
                    "Alliance forces attempt to secure Andorhal through a sustained campaign that "
                    "combines plague containment, civilian extraction, supply-line defense, and "
                    "repeated assaults on fortified undead positions. The arc highlights command "
                    "friction, battlefield reversals, and difficult tradeoffs between holding "
                    "ground and protecting vulnerable settlements while pressure escalates across "
                    "nearby routes."
                ),
                "start_anchor": "Andorhal",
                "story_beats": ["Secure route junctions", "Stabilize command posts"],
                "inclusion_decision": {
                    "inclusion_score": 10,
                    "criteria_breakdown": {
                        "importance": 2,
                        "coherence": 2,
                        "evidence": 2,
                        "relevance": 2,
                        "pilot_fit": 2,
                    },
                    "include_decision": "include",
                    "decision_reason": "Meets sub-zone threshold with strong evidence.",
                    "source_refs": [
                        {
                            "source_id": "src-wiki-wpl",
                            "locator": "section:quests paragraph:2",
                            "revision_id": "oldid:777",
                            "excerpt_hash": "sha256:subzone9999",
                        }
                    ],
                },
                "depends_on_parent_context": False,
            }
        ],
        "major_questlines_horde": [],
        "major_questlines_shared": [],
        "major_characters": [
            {
                "id": "character-thassarian",
                "name": "Thassarian",
                "summary": (
                    "Alliance commander whose tactical priorities influence control of Andorhal's "
                    "frontline sectors."
                ),
            }
        ],
        "instances": [],
        "major_landmarks": [
            {
                "id": "landmark-andorhal",
                "name": "Andorhal",
                "summary": (
                    "Battle-scarred urban center defining regional strategy and supply movement."
                ),
            }
        ],
        "glossary": [{"term_id": "term-scourge"}],
        "sources": [
            {
                "source_id": "src-wiki-wpl",
                "url": "https://wowpedia.fandom.com/wiki/Western_Plaguelands",
                "revision_id": "oldid:777",
            }
        ],
        "provenance": {
            "at_a_glance": [
                {
                    "source_id": "src-wiki-wpl",
                    "locator": "section:lead paragraph:1",
                    "revision_id": "oldid:777",
                    "excerpt_hash": "sha256:subzone1111",
                }
            ],
            "currently": [
                {
                    "source_id": "src-wiki-wpl",
                    "locator": "section:currently paragraph:1",
                    "revision_id": "oldid:777",
                    "excerpt_hash": "sha256:subzone2222",
                }
            ],
            "history": [
                {
                    "source_id": "src-wiki-wpl",
                    "locator": "section:history paragraph:1",
                    "revision_id": "oldid:777",
                    "excerpt_hash": "sha256:subzone3333",
                },
                {
                    "source_id": "src-wiki-wpl",
                    "locator": "section:history paragraph:2",
                    "revision_id": "oldid:777",
                    "excerpt_hash": "sha256:subzone4444",
                },
            ],
            "major_questlines_alliance": {
                "ql-andorhal-alliance-subzone": [
                    {
                        "source_id": "src-wiki-wpl",
                        "locator": "section:quests paragraph:2",
                        "revision_id": "oldid:777",
                        "excerpt_hash": "sha256:subzone5555",
                    }
                ]
            },
            "major_questlines_horde": {},
            "major_questlines_shared": {},
            "major_characters": {
                "character-thassarian": [
                    {
                        "source_id": "src-wiki-wpl",
                        "locator": "section:characters paragraph:1",
                        "revision_id": "oldid:777",
                        "excerpt_hash": "sha256:subzone6666",
                    }
                ]
            },
            "instances": {},
            "major_landmarks": {
                "landmark-andorhal": [
                    {
                        "source_id": "src-wiki-wpl",
                        "locator": "section:landmarks paragraph:1",
                        "revision_id": "oldid:777",
                        "excerpt_hash": "sha256:subzone7777",
                    }
                ]
            },
            "glossary": {
                "term-scourge": [
                    {
                        "source_id": "src-wiki-wpl",
                        "locator": "section:glossary paragraph:1",
                        "revision_id": "oldid:777",
                        "excerpt_hash": "sha256:subzone8888",
                    }
                ]
            },
        },
    }


def test_zone_happy_fixture_passes_validation() -> None:
    report = validate_payload("zone", _load_fixture("happy", "zone_valid.json"))
    assert report.passed is True
    assert report.hard_fail_count == 0


def test_zone_edge_fixture_only_warns() -> None:
    report = validate_payload("zone", _load_fixture("edge", "zone_budget_warn.json"))
    assert report.passed is True
    assert report.hard_fail_count == 0
    assert report.warn_count >= 1


def test_zone_failure_fixture_hard_fails_provenance() -> None:
    report = validate_payload("zone", _load_fixture("failure", "zone_missing_provenance.json"))
    assert report.passed is False
    assert report.hard_fail_count >= 1
    assert any(issue.code.startswith("provenance.") for issue in report.issues)
    assert any(issue.path == "$.provenance.glossary.term-scourge" for issue in report.issues)


def test_ambiguity_fixture_passes_glossary_validation() -> None:
    report = validate_payload(
        "glossary_term", _load_fixture("ambiguity", "glossary_ambiguity.json")
    )
    assert report.passed is True
    assert report.hard_fail_count == 0


def test_asset_passes_when_provenance_meets_minimums() -> None:
    report = validate_payload("asset", _valid_asset_payload())
    assert report.passed is True
    assert report.hard_fail_count == 0


def test_asset_fails_when_metadata_pointers_missing() -> None:
    payload = _valid_asset_payload()
    payload["provenance"]["metadata"] = []
    report = validate_payload("asset", payload)
    assert report.passed is False
    assert any(issue.code == "provenance.missing_section_pointers" for issue in report.issues)


def test_asset_warns_when_caption_pointers_exist_without_body() -> None:
    payload = _valid_asset_payload()
    del payload["caption"]
    report = validate_payload("asset", payload)
    assert report.passed is True
    codes = {issue.code for issue in report.issues}
    assert "provenance.optional_section_warning" in codes


def test_asset_fails_when_pointer_source_id_not_in_manifest() -> None:
    payload = _valid_asset_payload()
    payload["provenance"]["metadata"][0]["source_id"] = "src-missing"
    report = validate_payload("asset", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "provenance.unknown_source_id" in codes


def test_sub_zone_incomplete_fixture_fails_schema() -> None:
    report = validate_payload("sub_zone", _load_fixture("failure", "sub_zone_invalid.json"))
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "schema.invalid" in codes


def test_sub_zone_exceeds_max_questline_cards() -> None:
    report = validate_payload(
        "sub_zone", _load_fixture("failure", "sub_zone_too_many_questlines.json")
    )
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "sub_zone.questline_max_cards" in codes


def test_release_gate_blocks_unresolved_provenance_override() -> None:
    report = validate_payload(
        "zone",
        _load_fixture("happy", "zone_valid.json"),
        validation_context={
            "release_gate": True,
            "unresolved_provenance_override": True,
        },
    )
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "provenance.unresolved_override_release_gate" in codes


def test_provenance_warns_on_stale_revision() -> None:
    payload = _valid_instance_payload()
    payload["provenance"]["story_context"][0]["revision_id"] = "rev-1"
    report = validate_payload("instance", payload)
    assert report.passed is True
    codes = {issue.code for issue in report.issues}
    assert "provenance.stale_source_revision" in codes


def test_provenance_warns_when_mixed_sources_not_present() -> None:
    payload = _valid_instance_payload()
    # story_context requires >=2 pointers by length and both pointers use one source_id.
    report = validate_payload("instance", payload)
    assert report.passed is True
    codes = {issue.code for issue in report.issues}
    assert "provenance.mixed_source_recommended" in codes


def test_sub_zone_requires_locked_sections_and_hook_budget() -> None:
    payload = _valid_sub_zone_payload()
    payload["at_a_glance"] = "   "
    payload["major_landmarks"] = []
    payload["major_questlines_alliance"][0]["hook"] = "Too short hook."
    report = validate_payload("sub_zone", payload)
    codes = {issue.code for issue in report.issues}
    assert "sub_zone.required_section_missing" in codes
    assert "sub_zone.questline_hook_budget" in codes


def test_sub_zone_faction_bucket_mismatch_fails() -> None:
    payload = _valid_sub_zone_payload()
    payload["major_questlines_alliance"][0]["faction"] = "horde"
    report = validate_payload("sub_zone", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "sub_zone.questline_faction_bucket" in codes


def test_sub_zone_provenance_missing_card_pointer_fails() -> None:
    payload = _valid_sub_zone_payload()
    payload["provenance"]["major_landmarks"]["landmark-andorhal"] = []
    report = validate_payload("sub_zone", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "provenance.missing_card_pointers" in codes


def test_sub_zone_warns_when_empty_bucket_has_provenance_entries() -> None:
    payload = _valid_sub_zone_payload()
    payload["provenance"]["major_questlines_horde"] = {
        "ql-placeholder-horde": [
            {
                "source_id": "src-wiki-wpl",
                "locator": "section:horde paragraph:1",
                "revision_id": "oldid:777",
                "excerpt_hash": "sha256:subzonehorde1111",
            }
        ]
    }
    report = validate_payload("sub_zone", payload)
    assert report.passed is True
    codes = {issue.code for issue in report.issues}
    assert "structure.conditional_rendering_warning" in codes


def test_sub_zone_inclusion_threshold_enforced() -> None:
    payload = _valid_sub_zone_payload()
    payload["major_questlines_alliance"][0]["inclusion_decision"]["criteria_breakdown"] = {
        "importance": 2,
        "coherence": 2,
        "evidence": 2,
        "relevance": 2,
    }
    payload["major_questlines_alliance"][0]["inclusion_decision"]["inclusion_score"] = 8
    report = validate_payload("sub_zone", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "sub_zone.inclusion_threshold" in codes


def test_sub_zone_dependency_note_required_when_parent_context_true() -> None:
    payload = _valid_sub_zone_payload()
    payload["major_questlines_alliance"][0]["depends_on_parent_context"] = True
    report = validate_payload("sub_zone", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "sub_zone.dependency_note_required" in codes


def test_zone_questline_inclusion_threshold_enforced() -> None:
    payload = _load_fixture("happy", "zone_valid.json")
    payload["major_questlines_alliance"][0]["inclusion_decision"]["criteria_breakdown"] = {
        "importance": 2,
        "coherence": 2,
        "evidence": 2,
        "relevance": 1,
    }
    payload["major_questlines_alliance"][0]["inclusion_decision"]["inclusion_score"] = 7
    report = validate_payload("zone", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "structure.zone_questline_inclusion_threshold" in codes


def test_zone_questline_dependency_note_required_when_parent_context_true() -> None:
    payload = _load_fixture("happy", "zone_valid.json")
    payload["major_questlines_alliance"][0]["depends_on_parent_context"] = True
    report = validate_payload("zone", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "structure.zone_questline_dependency_note_required" in codes
