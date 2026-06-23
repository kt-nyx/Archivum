"""Shared minimal valid wiki-first page payloads for tests."""

from __future__ import annotations

from typing import Any


def minimal_zone_page_payload(*, zone_id: str = "zone-testlands") -> dict[str, Any]:
    return {
        "zone_id": zone_id,
        "name": "Testlands",
        "wiki_url": f"https://example.test/{zone_id}",
        "parent_continent": "eastern-kingdoms",
        "expansion_context": "retail",
        "at_a_glance": "Testlands remain a contested frontier where patrols hold key routes.",
        "currently": "Patrols continue to secure roads while hostile forces pressure nearby settlements.",
        "history_sections": [
            {
                "heading": "Early Conflict",
                "body": (
                    "The region suffered repeated invasions before patrol networks stabilized "
                    "supply lines and defensive positions across the frontier."
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
                "url": f"https://example.test/{zone_id}",
                "revision_id": "mw:42",
            }
        ],
        "provenance": {
            "at_a_glance": [
                {
                    "source_id": "src-zone",
                    "locator": "section:lead paragraph:1",
                    "revision_id": "mw:42",
                    "excerpt_hash": "sha256:zonepage111111111",
                }
            ],
            "currently": [
                {
                    "source_id": "src-zone",
                    "locator": "section:quests paragraph:1",
                    "revision_id": "mw:42",
                    "excerpt_hash": "sha256:zonepage222222222",
                }
            ],
            "history": [
                {
                    "source_id": "src-zone",
                    "locator": "section:history paragraph:1",
                    "revision_id": "mw:42",
                    "excerpt_hash": "sha256:zonepage333333333",
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


def minimal_instance_page_payload(*, instance_id: str = "instance-test-dungeon") -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "name": "Test Dungeon",
        "instance_type": "dungeon",
        "parent_zone_id": "zone-testlands",
        "expansion_context": "retail",
        "wiki_url": f"https://example.test/{instance_id}",
        "at_a_glance": "Test Dungeon remains a hostile stronghold tied to regional conflict.",
        "overview": " ".join(
            [
                "Test Dungeon was founded as a fortified academy where hostile instructors trained "
                "forces, coordinated raids, and sustained pressure on nearby settlements across "
                "repeated campaign cycles while patrols attempted to break ritual control.",
            ]
            * 3
        ),
        "history_sections": [
            {
                "heading": "Fortified Academy",
                "body": (
                    "The dungeon evolved into a fortified academy where hostile instructors trained "
                    "forces, coordinated raids, and sustained pressure on nearby settlements while "
                    "expanding ritual networks and reinforcing commanders across repeated cycles."
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
                "url": f"https://example.test/{instance_id}",
                "revision_id": "mw:99",
            }
        ],
        "provenance": {
            "identity_header": [
                {
                    "source_id": "src-instance",
                    "locator": "section:lead paragraph:1",
                    "revision_id": "mw:99",
                    "excerpt_hash": "sha256:instancepage1111111",
                }
            ],
            "story_context": [
                {
                    "source_id": "src-instance",
                    "locator": "section:overview paragraph:1",
                    "revision_id": "mw:99",
                    "excerpt_hash": "sha256:instancepage2222222",
                }
            ],
            "key_characters": {},
            "major_factions": {},
            "glossary": {},
        },
    }
