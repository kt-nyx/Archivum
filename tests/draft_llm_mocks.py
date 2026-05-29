"""Shared OpenAI draft mocks keyed by ``response_schema_name``."""

from __future__ import annotations

from typing import Any


def _inclusion() -> dict[str, Any]:
    return {
        "inclusion_score": 8,
        "criteria_breakdown": [
            {"criterion": "importance", "score": 2},
            {"criterion": "coherence", "score": 2},
            {"criterion": "evidence", "score": 2},
            {"criterion": "relevance", "score": 2},
        ],
        "include_decision": "include",
        "decision_reason": "Evidence-backed campaign arc.",
        "source_refs": [],
    }


def _questline_card(
    card_id: str,
    *,
    faction: str,
    title: str,
) -> dict[str, Any]:
    return {
        "id": card_id,
        "faction": faction,
        "title": title,
        "hook": f"{title} hook with enough words for validation.",
        "start_anchor": "Field Command",
        "story_beats": ["Assess", "Stabilize", "Consolidate"],
        "inclusion_decision": _inclusion(),
        "depends_on_parent_context": False,
        "dependency_note": "",
    }


def zone_draft_body() -> dict[str, Any]:
    return {
        "expansion": "retail",
        "at_a_glance": "An actively contested lore region under sustained pressure.",
        "currently": (
            "Current campaigns prioritize route security and settlement stabilization."
        ),
        "history": (
            "Historical conflict cycles and command shifts define present strategic stakes."
        ),
        "major_questlines_alliance": [
            _questline_card("ql-zone-alliance-core", faction="alliance", title="Alliance Core")
        ],
        "major_questlines_horde": [],
        "major_questlines_shared": [],
        "major_characters": [
            {
                "id": "character-zone-figure-one",
                "name": "Zone Figure One",
                "summary": "Leads campaign stabilization efforts.",
            },
            {
                "id": "character-zone-figure-two",
                "name": "Zone Figure Two",
                "summary": "Coordinates strategic responses.",
            },
            {
                "id": "character-zone-figure-three",
                "name": "Zone Figure Three",
                "summary": "Documents conflict outcomes.",
            },
        ],
        "instances": [
            {
                "id": "instance-zone-associated",
                "name": "Associated Instance",
                "summary": "Related conflict site tied to campaign outcomes.",
            }
        ],
        "major_landmarks": [
            {
                "id": "landmark-zone-site-one",
                "name": "Zone Site One",
                "summary": "Strategic site under ongoing pressure.",
            },
            {
                "id": "landmark-zone-site-two",
                "name": "Zone Site Two",
                "summary": "Operational hub for recovery efforts.",
            },
            {
                "id": "landmark-zone-site-three",
                "name": "Zone Site Three",
                "summary": "Frontline location for active campaigns.",
            },
        ],
        "glossary": [],
    }


def zone_draft_plan() -> dict[str, Any]:
    return {
        "expansion": "retail",
        "prose_outline": ["Regional recovery", "Faction pressure"],
        "major_questlines_alliance": [
            {
                "id": "ql-zone-alliance-core",
                "faction": "alliance",
                "title": "Alliance Core Campaign",
                "include_decision": "include",
            }
        ],
        "major_questlines_horde": [],
        "major_questlines_shared": [],
        "major_characters": [
            {"id": "character-zone-figure-one", "name": "Zone Figure One"},
            {"id": "character-zone-figure-two", "name": "Zone Figure Two"},
            {"id": "character-zone-figure-three", "name": "Zone Figure Three"},
        ],
        "instances": [{"id": "instance-zone-associated", "name": "Associated Instance"}],
        "major_landmarks": [
            {"id": "landmark-zone-site-one", "name": "Zone Site One"},
            {"id": "landmark-zone-site-two", "name": "Zone Site Two"},
            {"id": "landmark-zone-site-three", "name": "Zone Site Three"},
        ],
        "glossary": [],
    }


def zone_draft_prose() -> dict[str, Any]:
    body = zone_draft_body()
    return {
        "at_a_glance": body["at_a_glance"],
        "currently": body["currently"],
        "history": body["history"],
    }


def zone_draft_links() -> dict[str, Any]:
    body = zone_draft_body()
    return {
        "major_characters": body["major_characters"],
        "instances": body["instances"],
        "major_landmarks": body["major_landmarks"],
        "glossary": body["glossary"],
    }


def fake_draft_chat_by_schema(
    *_args: object,
    chat_result: dict[str, Any] | None = None,
    **kwargs: object,
) -> dict[str, Any] | None:
    if chat_result is not None:
        return chat_result
    schema_name = str(kwargs.get("response_schema_name", ""))
    if schema_name == "zone_draft_body":
        return zone_draft_body()
    if schema_name == "zone_draft_plan":
        return zone_draft_plan()
    if schema_name == "zone_draft_prose":
        return zone_draft_prose()
    if schema_name == "zone_draft_links":
        return zone_draft_links()
    if schema_name == "zone_draft_questlines_alliance":
        return {
            "cards": [
                _questline_card(
                    "ql-zone-alliance-core",
                    faction="alliance",
                    title="Alliance Core Campaign",
                )
            ]
        }
    if schema_name in {"zone_draft_questlines_horde", "zone_draft_questlines_shared"}:
        return {"cards": []}
    if schema_name == "instance_draft_body":
        return {
            "type": "dungeon",
            "identity_header": "A high-risk instance with concentrated hostile leadership.",
            "story_context": (
                "The instance story context covers campaign escalation, command response, "
                "and the strategic consequences of unresolved threats."
            ),
            "key_characters": [
                {
                    "id": "character-instance-key-one",
                    "name": "Instance Key One",
                    "summary": "Drives the instance's central conflict trajectory.",
                },
                {
                    "id": "character-instance-key-two",
                    "name": "Instance Key Two",
                    "summary": "Shapes the operational stakes within the dungeon.",
                },
            ],
            "glossary": [],
        }
    if schema_name == "sub_zone_draft_body":
        body = zone_draft_body()
        body.pop("expansion", None)
        return body
    if schema_name == "sub_zone_draft_plan":
        plan = zone_draft_plan()
        plan.pop("expansion", None)
        return plan
    if schema_name == "character_draft_body":
        return {
            "summary": "A notable figure in regional campaigns.",
            "short_history": "Their history spans multiple conflict cycles in the zone.",
            "glossary": [],
        }
    if schema_name == "glossary_term_draft_body":
        return {
            "category": "faction",
            "aliases": ["term-alias"],
            "summary": "A concise glossary summary.",
            "brief_history": "Brief historical context for the term.",
        }
    if schema_name == "asset_draft_body":
        return {
            "asset_type": "image",
            "title": "Pilot Asset",
            "license": "CC BY-SA 4.0",
            "credit": "Contributor",
            "allowed_use": True,
            "allowed_use_reason": "Licensed for reuse with attribution.",
            "proof_ref": "proof://pilot",
            "associated_entity_ids": ["zone-western-plaguelands"],
            "caption": "",
        }
    return None
