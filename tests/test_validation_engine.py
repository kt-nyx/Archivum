import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pipeline.validate.engine import validate_payload
from pipeline.validate.types import ValidationSeverity

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


def _valid_zone_page_payload() -> dict[str, Any]:
    return {
        "zone_id": "zone-western-plaguelands",
        "name": "Western Plaguelands",
        "wiki_url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
        "parent_continent": "eastern-kingdoms",
        "expansion_context": "retail",
        "at_a_glance": (
            "Blighted farmland now contested by crusaders and undead remnants across Lordaeron."
        ),
        "currently": (
            "Argent operations continue to stabilize roads while hostile forces pressure key routes "
            "and surrounding settlements."
        ),
        "history_sections": [
            {
                "heading": "Blight and Recovery",
                "body": (
                    "The region suffered catastrophic plague-era collapse before sustained military "
                    "and druidic campaigns began long-term restoration efforts."
                ),
                "source_refs": [],
            }
        ],
        "major_factions": [],
        "major_questlines": [],
        "location_cards": [],
        "instance_links": [],
        "glossary_refs": [],
        "sources": [
            {
                "source_id": "src-zone",
                "url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
                "revision_id": "mw:42",
            }
        ],
        "provenance": {
            "at_a_glance": [
                {
                    "source_id": "src-zone",
                    "locator": "section:lead paragraph:1",
                    "revision_id": "mw:42",
                    "excerpt_hash": "sha1:zonepage111111111",
                }
            ],
            "currently": [
                {
                    "source_id": "src-zone",
                    "locator": "section:quests paragraph:1",
                    "revision_id": "mw:42",
                    "excerpt_hash": "sha1:zonepage222222222",
                }
            ],
            "history": [
                {
                    "source_id": "src-zone",
                    "locator": "section:history paragraph:1",
                    "revision_id": "mw:42",
                    "excerpt_hash": "sha1:zonepage333333333",
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


_VALIDATION_ZONE_PAGE_CURRENTLY = (
    "Argent Crusade patrols and Cenarion restoration crews have reopened key roads and fields "
    "in Western Plaguelands, but Andorhal remains a militarized flashpoint and nearby settlements "
    "still plan around Scourge remnants. Hearthglen and Caer Darrow routes stay active under escort "
    "discipline, and local stability depends on constant patrol rotations rather than durable peacetime "
    "conditions. Farmers and caravan teams continue to coordinate movement windows with armed protection."
)
_VALIDATION_ZONE_PAGE_HISTORY_BODY = (
    "Before the Third War, Western Plaguelands served Lordaeron as a grain and trade heartland centered "
    "on Andorhal. Cult of the Damned infiltration and plague distribution transformed that network into "
    "contested undead territory, followed by prolonged control struggles among Scourge forces, Scarlet "
    "remnants, and anti-plague campaigns. After Wrath and into Cataclysm continuity, reclamation expanded "
    "under Argent and Cenarion efforts, yet conflict legacies around Andorhal and Scholomance-adjacent "
    "corridors kept security uneven and governance fragile."
)


def _validation_ready_zone_page_payload() -> dict[str, Any]:
    """Inline zone_page payload for validation-engine tests (replaces legacy zone_valid.json)."""
    payload = _valid_zone_page_payload()
    payload["at_a_glance"] = (
        "A recovering Lordaeron frontier where reclaimed fields, haunted keeps, and contested "
        "roads carry the scars of plague wars and later rebuilding efforts across the region."
    )
    payload["currently"] = _VALIDATION_ZONE_PAGE_CURRENTLY
    payload["history_sections"] = [
        {
            "heading": "Regional Collapse",
            "body": _VALIDATION_ZONE_PAGE_HISTORY_BODY,
            "source_refs": [],
        }
    ]
    payload["glossary_refs"] = [
        {
            "term_id": "term-scourge",
            "label": "Scourge",
            "wiki_url": "https://warcraft.wiki.gg/wiki/Scourge",
        }
    ]
    payload["sources"] = [
        {
            "source_id": "src-wiki-wpl",
            "url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
            "revision_id": "oldid:111",
        },
        {
            "source_id": "src-wiki-scholomance",
            "url": "https://warcraft.wiki.gg/wiki/Scholomance",
            "revision_id": "oldid:222",
        },
    ]
    provenance = payload["provenance"]
    for section in ("at_a_glance", "currently"):
        provenance[section] = [
            {
                "source_id": "src-wiki-wpl",
                "locator": f"section:{section} paragraph:1",
                "revision_id": "oldid:111",
                "excerpt_hash": f"sha256:zonepage{section[:4]}1111",
            }
        ]
    provenance["history"] = [
        {
            "source_id": "src-wiki-wpl",
            "locator": "section:history paragraph:1",
            "revision_id": "oldid:111",
            "excerpt_hash": "sha256:zonepagehist1111",
        }
    ]
    provenance["glossary"] = {
        "term-scourge": [
            {
                "source_id": "src-wiki-wpl",
                "locator": "section:glossary paragraph:1",
                "revision_id": "oldid:111",
                "excerpt_hash": "sha256:5555555555555555",
            }
        ]
    }
    return payload


def _sub_zone_invalid_payload() -> dict[str, Any]:
    return {
        "id": "subzone-andorhal",
        "name": "Andorhal",
        "major_questlines_alliance": [
            {"id": "ql-andorhal-alliance", "title": "Battle for Andorhal (Alliance)"},
            {"id": "ql-andorhal-militia", "title": "Andorhal Militia Push"},
        ],
        "major_questlines_horde": [
            {"id": "ql-andorhal-horde", "title": "Battle for Andorhal (Horde)"},
        ],
        "major_questlines_shared": [],
    }


def _sub_zone_too_many_questlines_payload() -> dict[str, Any]:
    payload = _valid_sub_zone_payload()
    base_card = payload["major_questlines_alliance"][0]
    payload["major_questlines_alliance"] = [
        {**base_card, "id": f"ql-cap-{index}", "title": f"Cap overload arc {index}"}
        for index in range(1, 5)
    ]
    return payload


def _valid_instance_page_payload() -> dict[str, Any]:
    return {
        "instance_id": "instance-scholomance",
        "name": "Scholomance",
        "instance_type": "dungeon",
        "parent_zone_id": "zone-western-plaguelands",
        "expansion_context": "retail",
        "wiki_url": "https://warcraft.wiki.gg/wiki/Scholomance",
        "at_a_glance": "Necromantic stronghold controlled by hostile undead leadership.",
        "overview": (
            "Adventurers assault the school to stop Darkmaster Gandling and disrupt ritual control "
            "over local undead forces."
        ),
        "history_sections": [
            {
                "heading": "Origins",
                "body": (
                    "Scholomance was established as a covert necromantic academy and later became a "
                    "persistent source of regional threat."
                ),
                "source_refs": [],
            }
        ],
        "key_characters": [],
        "major_factions": [],
        "lore_source": "instance_page",
        "lore_source_reason": None,
        "variant_policy": "standalone",
        "variant_reason_codes": [],
        "glossary_refs": [],
        "sources": [
            {
                "source_id": "src-instance",
                "url": "https://warcraft.wiki.gg/wiki/Scholomance",
                "revision_id": "mw:99",
            }
        ],
        "provenance": {
            "identity_header": [
                {
                    "source_id": "src-instance",
                    "locator": "section:lead paragraph:1",
                    "revision_id": "mw:99",
                    "excerpt_hash": "sha1:instancepage1111111",
                }
            ],
            "story_context": [
                {
                    "source_id": "src-instance",
                    "locator": "section:overview paragraph:1",
                    "revision_id": "mw:99",
                    "excerpt_hash": "sha1:instancepage2222222",
                }
            ],
            "key_characters": {},
            "major_factions": {},
            "glossary": {},
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


def test_zone_page_happy_payload_passes_validation() -> None:
    report = validate_payload("zone_page", _validation_ready_zone_page_payload())
    assert report.passed is True
    assert report.hard_fail_count == 0


def test_zone_page_edge_payload_only_warns() -> None:
    payload = _validation_ready_zone_page_payload()
    payload["at_a_glance"] = "Scarred frontier under uneasy recovery."
    report = validate_payload("zone_page", payload)
    assert report.passed is True
    assert report.hard_fail_count == 0
    assert report.warn_count >= 1


def test_zone_page_failure_hard_fails_missing_glossary_provenance() -> None:
    payload = _validation_ready_zone_page_payload()
    payload["provenance"]["glossary"] = {}
    report = validate_payload("zone_page", payload)
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


def test_sub_zone_incomplete_payload_fails_schema() -> None:
    report = validate_payload("sub_zone", _sub_zone_invalid_payload())
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "schema.invalid" in codes


def test_sub_zone_exceeds_max_questline_cards() -> None:
    report = validate_payload("sub_zone", _sub_zone_too_many_questlines_payload())
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "sub_zone.questline_max_cards" in codes


def test_release_gate_blocks_unresolved_provenance_override() -> None:
    report = validate_payload(
        "zone_page",
        _validation_ready_zone_page_payload(),
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


def test_zone_page_questline_inclusion_threshold_enforced() -> None:
    payload = _validation_ready_zone_page_payload()
    payload["major_questlines"] = [
        {
            "id": "cluster-part-1",
            "title": "Part 1 - Example Arc",
            "faction": "alliance",
            "cta_hook": "Crusaders push back undead forces along the ruined road network.",
            "start_anchor": "Quest A",
            "chain_refs": ["quest-a"],
            "include_decision": "exclude",
            "reason_codes": ["graph_depth"],
            "wiki_refs": ["/wiki/Quest_A"],
        }
    ]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "structure.zone_page_questline_inclusion_threshold" in codes


def test_fact_check_warn_profile_routes_contradiction_to_warning() -> None:
    payload = _validation_ready_zone_page_payload()
    payload["history_sections"][0]["body"] = (
        f"{payload['history_sections'][0]['body']} [CONTRADICTED]"
    )
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={"fact_check_profile": "warn"},
    )
    assert report.passed is True
    assert report.fact_check_report is not None
    codes = {issue.code for issue in report.issues}
    assert "fact_check.contradiction" in codes
    contradiction_issue = next(
        issue for issue in report.issues if issue.code == "fact_check.contradiction"
    )
    assert contradiction_issue.severity.value == "warn"


def test_fact_check_strict_profile_blocks_contradictions() -> None:
    payload = _validation_ready_zone_page_payload()
    payload["currently"] = f"{payload['currently']} [CONTRADICTED]"
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={"fact_check_profile": "strict"},
    )
    assert report.passed is False
    contradiction_issue = next(
        issue for issue in report.issues if issue.code == "fact_check.contradiction"
    )
    assert contradiction_issue.severity.value == "hard-fail"


def test_fact_check_uses_local_snapshots_for_evidence() -> None:
    payload = _validation_ready_zone_page_payload()
    source_ids = [entry["source_id"] for entry in payload["sources"]]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            "fact_check_source_snapshots": [
                {
                    "source_id": source_ids[0],
                    "url": "https://example.test/wpl",
                    "body": (
                        "Western Plaguelands is a contested region with strategic patrol routes, "
                        "military recovery campaigns, and zone history tied to repeated conflict."
                    ),
                },
                {
                    "source_id": source_ids[1],
                    "url": "https://example.test/scholomance",
                    "body": (
                        "Scholomance and surrounding campaigns define high-impact historical arcs "
                        "for the region."
                    ),
                },
            ],
        },
    )
    assert report.fact_check_report is not None
    rows = cast(list[dict[str, object]], report.fact_check_report["claims"])
    assert rows
    assert any(row["status"] == "supported" for row in rows)


def test_fact_check_warns_when_web_toggle_enabled_without_google_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    payload = _validation_ready_zone_page_payload()
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            "fact_check_web_search": True,
            "fact_check_target_entity_ids": [str(payload["zone_id"])],
        },
    )
    codes = {issue.code for issue in report.issues}
    assert "fact_check.web_unavailable" in codes


def test_fact_check_warn_profile_runs_llm_for_low_confidence_supported_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _validation_ready_zone_page_payload()
    source_ids = [entry["source_id"] for entry in payload["sources"]]
    settings = SimpleNamespace(
        openai_ready=True,
        google_ready=False,
        openai_model="gpt-5.5",
        google_api_key="",
        google_cse_id="",
    )
    monkeypatch.setattr("pipeline.validate.rules.fact_check.load_ai_settings", lambda: settings)
    llm_calls = {"count": 0}

    def fake_chat(*_args: object, **_kwargs: object) -> dict[str, object]:
        llm_calls["count"] += 1
        return {
            "status": "supported",
            "confidence": 0.91,
            "reason": "Evidence supports the claim.",
        }

    monkeypatch.setattr("pipeline.validate.rules.fact_check.chat_json_completion", fake_chat)
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            "fact_check_enable_llm": True,
            "fact_check_target_entity_ids": [str(payload["zone_id"])],
            "fact_check_source_snapshots": [
                {
                    "source_id": source_ids[0],
                    "url": "https://example.test/wpl",
                    "body": "Western Plaguelands remains contested across campaign fronts.",
                },
                {
                    "source_id": source_ids[1],
                    "url": "https://example.test/wpl-2",
                    "body": "Commanders maintain route security under sustained pressure.",
                },
            ],
        },
    )
    assert report.fact_check_report is not None
    assert llm_calls["count"] > 0


def test_fact_check_warn_profile_skips_llm_for_non_target_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _validation_ready_zone_page_payload()
    settings = SimpleNamespace(
        openai_ready=True,
        google_ready=False,
        openai_model="gpt-5.5",
        google_api_key="",
        google_cse_id="",
    )
    monkeypatch.setattr("pipeline.validate.rules.fact_check.load_ai_settings", lambda: settings)
    llm_calls = {"count": 0}

    def fake_chat(*_args: object, **_kwargs: object) -> dict[str, object]:
        llm_calls["count"] += 1
        return {
            "status": "supported",
            "confidence": 0.91,
            "reason": "Evidence supports the claim.",
        }

    monkeypatch.setattr("pipeline.validate.rules.fact_check.chat_json_completion", fake_chat)
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            "fact_check_enable_llm": True,
            "fact_check_target_entity_ids": ["zone-other"],
        },
    )
    assert report.fact_check_report is not None
    assert llm_calls["count"] == 0
    assert report.fact_check_report["targeted_for_adjudication"] is False


def test_similarity_warns_on_high_token_overlap_with_ingest_body() -> None:
    payload = copy.deepcopy(_validation_ready_zone_page_payload())
    payload["at_a_glance"] = "one two three four five six seven eight nine ten"
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_source_snapshots": [
                {
                    "source_id": "src-wiki-wpl",
                    "url": "https://example.test/wpl",
                    "body": (
                        "one two three four five six seven eight nine ten eleven twelve "
                        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
                    ),
                }
            ],
        },
    )
    codes = {issue.code for issue in report.issues}
    assert "similarity.verbatim_overlap_warn" in codes
    assert "similarity.verbatim_overlap_hard" not in codes


def test_similarity_hard_fails_on_near_verbatim_ingest_body() -> None:
    shared = (
        "identical verbatim block alpha bravo charlie delta echo foxtrot golf hotel "
        "india juliet kilo lima mike november oscar papa quebec romeo sierra tango"
    )
    payload = copy.deepcopy(_validation_ready_zone_page_payload())
    payload["at_a_glance"] = shared
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_source_snapshots": [
                {
                    "source_id": "src-wiki-wpl",
                    "url": "https://example.test/wpl",
                    "body": shared,
                }
            ],
        },
    )
    codes = {issue.code for issue in report.issues}
    assert "similarity.verbatim_overlap_hard" in codes


def test_similarity_clean_when_draft_diverges_from_ingest_body() -> None:
    payload = copy.deepcopy(_validation_ready_zone_page_payload())
    payload["at_a_glance"] = (
        "xyzzy quux plugh frobnitz wibble nimbus vortex shard prism lattice aurora"
    )
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_source_snapshots": [
                {
                    "source_id": "src-wiki-wpl",
                    "url": "https://example.test/wpl",
                    "body": (
                        "Western Plaguelands is a contested region with strategic patrol routes, "
                        "military recovery campaigns, and zone history tied to repeated conflict."
                    ),
                }
            ],
        },
    )
    codes = {issue.code for issue in report.issues}
    assert not any(code.startswith("similarity.") for code in codes)


def test_similarity_emits_unavailable_when_snapshots_required_but_missing() -> None:
    payload = copy.deepcopy(_validation_ready_zone_page_payload())
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            "similarity_require_snapshots": True,
            "fact_check_source_snapshots": [],
        },
    )
    issues = [i for i in report.issues if i.code == "similarity.ingest_snapshots_unavailable"]
    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.WARN


def test_similarity_stage_context_strict_profile_unavailable_snapshots_is_hard_fail() -> None:
    """Mirrors run_validate_stage keys: strict escalates missing ingest bodies to hard-fail."""
    payload = copy.deepcopy(_validation_ready_zone_page_payload())
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "strict",
            "similarity_require_snapshots": True,
            "fact_check_source_snapshots": [],
        },
    )
    inv = [i for i in report.issues if i.code == "similarity.ingest_snapshots_unavailable"]
    assert len(inv) == 1
    assert inv[0].severity == ValidationSeverity.HARD_FAIL
    assert report.passed is False


def test_similarity_skipped_without_issue_when_snapshots_absent_by_default() -> None:
    report = validate_payload("zone_page", _validation_ready_zone_page_payload())
    assert not any(issue.code.startswith("similarity.") for issue in report.issues)


def test_zone_page_structure_requires_history_sections() -> None:
    payload = _valid_zone_page_payload()
    payload["history_sections"] = []
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "structure.required_section_empty" in codes


def test_zone_page_alliance_questline_uses_alliance_provenance_bucket() -> None:
    payload = _valid_zone_page_payload()
    payload["major_questlines"] = [
        {
            "id": "cluster-part-1",
            "title": "Part 1 - Example Arc",
            "faction": "alliance",
            "cta_hook": "Crusaders push back undead forces along the ruined road.",
            "start_anchor": "Quest A",
            "chain_refs": ["quest-a"],
            "include_decision": "include",
            "reason_codes": ["graph_depth"],
            "wiki_refs": ["/wiki/Quest_A"],
        }
    ]
    payload["provenance"]["major_questlines_alliance"] = {
        "cluster-part-1": [
            {
                "source_id": "src-zone",
                "locator": "section:description paragraph:1",
                "revision_id": "mw:42",
                "excerpt_hash": "sha1:questline111111111",
            }
        ]
    }
    report = validate_payload("zone_page", payload)
    codes = {issue.code for issue in report.issues}
    assert "provenance.missing_card_pointers" not in codes


def test_instance_page_budget_and_provenance_rules_are_applied() -> None:
    payload = _valid_instance_page_payload()
    payload["overview"] = "Too short."
    payload["sources"] = []
    report = validate_payload("instance_page", payload)
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "budget.section" in codes
    assert "provenance.missing_sources_manifest" in codes


def test_instance_page_overview_within_story_context_budget_passes() -> None:
    payload = _valid_instance_page_payload()
    payload["overview"] = " ".join(
        [
            "The Archive Vault was founded as a school for battle-mages who studied forbidden necromancy",
            "after the kingdom fell to plague and civil war across the blighted countryside.",
        ]
        * 10
    )
    report = validate_payload("instance_page", payload)
    overview_issues = [
        issue
        for issue in report.issues
        if issue.path == "$.overview" and issue.code == "budget.section"
    ]
    assert not overview_issues


def test_instance_page_story_context_pointer_cap_warns_when_exceeded() -> None:
    payload = _valid_instance_page_payload()
    payload["provenance"]["story_context"] = [
        {
            "source_id": "src-instance",
            "locator": f"section:overview paragraph:{index}",
            "revision_id": "mw:99",
            "excerpt_hash": f"sha1:instancepage{index:07d}",
        }
        for index in range(1, 5)
    ]
    report = validate_payload("instance_page", payload)
    assert any(
        issue.code == "provenance.pointer_cap_exceeded" and issue.path == "$.provenance.story_context"
        for issue in report.issues
    )


def test_instance_page_story_context_pointer_cap_passes_at_three() -> None:
    payload = _valid_instance_page_payload()
    payload["provenance"]["story_context"] = [
        {
            "source_id": "src-instance",
            "locator": f"section:overview paragraph:{index}",
            "revision_id": "mw:99",
            "excerpt_hash": f"sha1:instancepage{index:07d}",
        }
        for index in range(1, 4)
    ]
    report = validate_payload("instance_page", payload)
    assert not any(
        issue.code == "provenance.pointer_cap_exceeded" and issue.path == "$.provenance.story_context"
        for issue in report.issues
    )


def test_instance_page_overview_passthrough_hard_fails() -> None:
    payload = _valid_instance_page_payload()
    payload["overview"] = (
        "and the school's halls still echo with necromantic rituals while adventurers press deeper"
    )
    report = validate_payload("instance_page", payload)
    assert report.passed is False
    passthrough_issues = [
        issue
        for issue in report.issues
        if issue.code == "structure.instance_page_overview_passthrough"
    ]
    assert passthrough_issues
    assert all(issue.severity == ValidationSeverity.HARD_FAIL for issue in passthrough_issues)


def test_instance_page_generic_overview_hard_fails() -> None:
    payload = _valid_instance_page_payload()
    payload["overview"] = (
        "Scholomance contains key enemies and encounter stakes captured from Warcraft Wiki."
    )
    report = validate_payload("instance_page", payload)
    codes = {issue.code for issue in report.issues}
    assert "structure.instance_page_generic_overview" in codes


def test_instance_page_generic_key_character_hard_fails() -> None:
    payload = _valid_instance_page_payload()
    payload["key_characters"] = [
        {
            "id": "character-gandling",
            "name": "Darkmaster Gandling",
            "summary": (
                "Darkmaster Gandling is a key enemy presence tied to the instance narrative."
            ),
            "role": "enemy",
            "wiki_ref": None,
            "decision_reason_codes": [],
            "thumbnail_asset_id": None,
        }
    ]
    report = validate_payload("instance_page", payload)
    codes = {issue.code for issue in report.issues}
    assert "structure.instance_page_generic_key_character" in codes


def test_instance_pointer_cap_uses_centralized_constant() -> None:
    from pipeline.contracts.models import INSTANCE_PROVENANCE_POINTER_CAP

    payload = _valid_instance_page_payload()
    payload["provenance"]["story_context"] = [
        {
            "source_id": "src-instance",
            "locator": f"section:overview paragraph:{index}",
            "revision_id": "mw:99",
            "excerpt_hash": f"sha1:instancepage{index:07d}",
        }
        for index in range(1, INSTANCE_PROVENANCE_POINTER_CAP + 2)
    ]
    report = validate_payload(
        "instance_page", payload, validation_context={"release_gate": True}
    )
    cap_issues = [
        issue
        for issue in report.issues
        if issue.code == "provenance.pointer_cap_exceeded"
        and issue.path == "$.provenance.story_context"
    ]
    assert cap_issues
    assert all(issue.severity == ValidationSeverity.HARD_FAIL for issue in cap_issues)


def test_zone_page_fact_check_uses_zone_id_as_entity_id() -> None:
    payload = _valid_zone_page_payload()
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            "fact_check_source_snapshots": [
                {
                    "source_id": "src-zone",
                    "url": "https://example.test/zone",
                    "body": (
                        "Blighted farmland now contested by crusaders and undead remnants across "
                        "Lordaeron and nearby roads."
                    ),
                }
            ],
        },
    )
    assert report.fact_check_report is not None
    assert report.fact_check_report["entity_id"] == "zone-western-plaguelands"


def _low_overlap_fact_check_context(source_id: str = "src-zone") -> dict[str, object]:
    return {
        "fact_check_source_snapshots": [
            {
                "source_id": source_id,
                "url": "https://example.test/unrelated",
                "body": (
                    "Unrelated encyclopedic content about distant continents, trade routes, "
                    "and historical events with no overlap to the draft narrative sections."
                ),
            }
        ],
    }


def test_fact_check_off_emits_no_insufficient_evidence_zone_page() -> None:
    payload = _valid_zone_page_payload()
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "off",
            **_low_overlap_fact_check_context(),
        },
    )
    codes = {issue.code for issue in report.issues}
    assert not any(code.startswith("fact_check.") for code in codes)
    assert report.fact_check_report is not None
    assert report.fact_check_report["profile"] == "off"
    assert report.fact_check_report["claim_count"] == 0


def test_fact_check_off_emits_no_insufficient_evidence_instance_page() -> None:
    payload = _valid_instance_page_payload()
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={
            "fact_check_profile": "off",
            **_low_overlap_fact_check_context("src-instance"),
        },
    )
    codes = {issue.code for issue in report.issues}
    assert not any(code.startswith("fact_check.") for code in codes)
    assert report.fact_check_report is not None
    assert report.fact_check_report["profile"] == "off"


def test_fact_check_warn_profile_emits_insufficient_evidence_on_low_overlap() -> None:
    payload = _valid_zone_page_payload()
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_profile": "warn",
            **_low_overlap_fact_check_context(),
        },
    )
    codes = {issue.code for issue in report.issues}
    assert "fact_check.insufficient_evidence" in codes


def test_instance_page_key_characters_empty_hard_fails_under_release_gate() -> None:
    payload = _valid_instance_page_payload()
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={"release_gate": True},
    )
    assert report.passed is False
    assert any(issue.code == "budget.instance_key_characters_empty" for issue in report.issues)


def test_zone_page_similarity_rules_execute_against_ingest_snapshots() -> None:
    payload = _valid_zone_page_payload()
    payload["at_a_glance"] = (
        "identical overlap block alpha bravo charlie delta echo foxtrot golf hotel india"
    )
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "fact_check_source_snapshots": [
                {
                    "source_id": "src-zone",
                    "url": "https://example.test/zone",
                    "body": (
                        "identical overlap block alpha bravo charlie delta echo foxtrot golf "
                        "hotel india juliet kilo lima mike november oscar papa"
                    ),
                }
            ],
        },
    )
    codes = {issue.code for issue in report.issues}
    assert any(code.startswith("similarity.verbatim_overlap") for code in codes)


def test_zone_page_currently_temporal_drift_and_overlap_warns() -> None:
    payload = _valid_zone_page_payload()
    payload["currently"] = (
        "Formerly, this region was established during the Third War and years ago it fell to blight "
        "before being contested by crusaders and undead remnants across Lordaeron."
    )
    payload["history_sections"][0]["body"] = payload["currently"]
    report = validate_payload("zone_page", payload)
    codes = {issue.code for issue in report.issues}
    assert "structure.zone_page_currently_temporal_drift" in codes
    assert "structure.zone_page_currently_history_overlap" in codes


def test_zone_page_missing_currently_provenance_hard_fails() -> None:
    payload = _valid_zone_page_payload()
    payload["provenance"]["currently"] = []
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(issue.code == "provenance.missing_section_pointers" for issue in report.issues)


def test_instance_page_missing_key_character_card_provenance_hard_fails() -> None:
    payload = _valid_instance_page_payload()
    payload["key_characters"] = [
        {
            "id": "character-darkmaster-gandling",
            "name": "Darkmaster Gandling",
            "summary": "Leader of the instance's necromantic hierarchy and primary objective.",
            "role": "enemy",
            "thumbnail_asset_id": None,
        }
    ]
    report = validate_payload("instance_page", payload)
    assert report.passed is False
    assert any(issue.code == "provenance.missing_card_pointers" for issue in report.issues)


def test_instance_page_invalid_character_role_rejected() -> None:
    payload = _valid_instance_page_payload()
    payload["key_characters"] = [
        {
            "id": "character-darkmaster-gandling",
            "name": "Darkmaster Gandling",
            "summary": "Leader of the instance's necromantic hierarchy and primary objective.",
            "role": "villain",
        }
    ]
    report = validate_payload("instance_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "schema.invalid" and "role" in issue.path for issue in report.issues
    )


def test_zone_page_generic_instance_link_hard_fails() -> None:
    payload = _valid_zone_page_payload()
    payload["instance_links"] = [
        {
            "id": "instance-example",
            "name": "Example Instance",
            "summary": "Example Instance anchors a key conflict thread linked to this zone.",
            "thumbnail_asset_id": None,
        }
    ]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(issue.code == "structure.zone_page_generic_instance_link" for issue in report.issues)


def test_zone_page_pointer_cap_hard_fails_under_release_gate() -> None:
    payload = _valid_zone_page_payload()
    payload["provenance"]["at_a_glance"] = [
        {
            "source_id": "src-zone",
            "locator": f"section:lead paragraph:{index}",
            "revision_id": "mw:42",
            "excerpt_hash": f"sha256:cap{index:012d}",
        }
        for index in range(4)
    ]
    report = validate_payload("zone_page", payload, validation_context={"release_gate": True})
    assert any(issue.code == "provenance.pointer_cap_exceeded" for issue in report.issues)


def test_zone_page_parent_continent_unknown_hard_fails() -> None:
    payload = _valid_zone_page_payload()
    payload["parent_continent"] = "unknown"
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(issue.code == "structure.zone_page_parent_continent_unresolved" for issue in report.issues)


def test_zone_page_glossary_ref_missing_wiki_url_hard_fails() -> None:
    payload = _valid_zone_page_payload()
    payload["glossary_refs"] = [{"term_id": "term-scourge", "label": "Scourge"}]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(issue.code == "structure.glossary_ref_missing_wiki_url" for issue in report.issues)
