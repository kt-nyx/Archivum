"""JSON Schema fragments for draft structured outputs."""

from __future__ import annotations

from typing import Any

SOURCE_POINTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source_id", "locator", "revision_id", "excerpt_hash"],
    "properties": {
        "source_id": {"type": "string", "minLength": 1},
        "locator": {"type": "string", "minLength": 1},
        "revision_id": {"type": "string", "minLength": 1},
        "excerpt_hash": {"type": "string", "minLength": 1},
    },
}

CRITERION_SCORE_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criterion", "score"],
    "properties": {
        "criterion": {"type": "string", "minLength": 1},
        "score": {"type": "integer", "minimum": 0, "maximum": 2},
    },
}

INCLUSION_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "inclusion_score",
        "criteria_breakdown",
        "include_decision",
        "decision_reason",
        "source_refs",
    ],
    "properties": {
        "inclusion_score": {"type": "integer", "minimum": 0, "maximum": 12},
        "criteria_breakdown": {"type": "array", "items": CRITERION_SCORE_ROW_SCHEMA},
        "include_decision": {"type": "string", "enum": ["include", "exclude"]},
        "decision_reason": {"type": "string", "minLength": 1},
        "source_refs": {"type": "array", "items": SOURCE_POINTER_SCHEMA},
    },
}

QUESTLINE_CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "faction",
        "title",
        "hook",
        "start_anchor",
        "story_beats",
        "inclusion_decision",
        "depends_on_parent_context",
        "dependency_note",
    ],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "faction": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "hook": {"type": "string", "minLength": 1},
        "start_anchor": {"type": "string", "minLength": 1},
        "story_beats": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "inclusion_decision": INCLUSION_DECISION_SCHEMA,
        "depends_on_parent_context": {"type": "boolean"},
        "dependency_note": {"type": "string"},
    },
}

QUESTLINE_STUB_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "faction", "title", "include_decision"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "faction": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "include_decision": {"type": "string", "enum": ["include", "exclude"]},
    },
}

LINK_CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "name", "summary"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "summary": {"type": "string", "minLength": 1},
    },
}

LINK_STUB_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "name"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
    },
}

GLOSSARY_TERM_ID_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["term_id"],
    "properties": {"term_id": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


def zone_draft_body_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "expansion",
            "at_a_glance",
            "currently",
            "history",
            "major_questlines_alliance",
            "major_questlines_horde",
            "major_questlines_shared",
            "major_characters",
            "instances",
            "major_landmarks",
            "glossary",
        ],
        "additionalProperties": False,
        "properties": {
            "expansion": {"type": "string", "minLength": 1},
            "at_a_glance": {"type": "string", "minLength": 1},
            "currently": {"type": "string", "minLength": 1},
            "history": {"type": "string", "minLength": 1},
            "major_questlines_alliance": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
            "major_questlines_horde": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
            "major_questlines_shared": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
            "major_characters": {"type": "array", "items": LINK_CARD_SCHEMA},
            "instances": {"type": "array", "items": LINK_CARD_SCHEMA},
            "major_landmarks": {"type": "array", "items": LINK_CARD_SCHEMA},
            "glossary": {"type": "array", "items": GLOSSARY_TERM_ID_SCHEMA},
        },
    }


def sub_zone_draft_body_schema() -> dict[str, Any]:
    schema = zone_draft_body_schema()
    props = dict(schema["properties"])
    props.pop("expansion", None)
    required = [k for k in schema["required"] if k != "expansion"]
    return {
        "type": "object",
        "required": required,
        "additionalProperties": False,
        "properties": props,
    }


def zone_draft_plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "expansion",
            "prose_outline",
            "major_questlines_alliance",
            "major_questlines_horde",
            "major_questlines_shared",
            "major_characters",
            "instances",
            "major_landmarks",
            "glossary",
        ],
        "additionalProperties": False,
        "properties": {
            "expansion": {"type": "string", "minLength": 1},
            "prose_outline": {
                "type": "array",
                "items": {"type": "string"},
            },
            "major_questlines_alliance": {"type": "array", "items": QUESTLINE_STUB_SCHEMA},
            "major_questlines_horde": {"type": "array", "items": QUESTLINE_STUB_SCHEMA},
            "major_questlines_shared": {"type": "array", "items": QUESTLINE_STUB_SCHEMA},
            "major_characters": {"type": "array", "items": LINK_STUB_SCHEMA},
            "instances": {"type": "array", "items": LINK_STUB_SCHEMA},
            "major_landmarks": {"type": "array", "items": LINK_STUB_SCHEMA},
            "glossary": {"type": "array", "items": GLOSSARY_TERM_ID_SCHEMA},
        },
    }


def sub_zone_draft_plan_schema() -> dict[str, Any]:
    schema = zone_draft_plan_schema()
    props = dict(schema["properties"])
    props.pop("expansion", None)
    required = [k for k in schema["required"] if k != "expansion"]
    return {
        "type": "object",
        "required": required,
        "additionalProperties": False,
        "properties": props,
    }


def zone_draft_prose_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["at_a_glance", "currently", "history"],
        "additionalProperties": False,
        "properties": {
            "at_a_glance": {"type": "string", "minLength": 1},
            "currently": {"type": "string", "minLength": 1},
            "history": {"type": "string", "minLength": 1},
        },
    }


def zone_draft_questlines_bucket_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["cards"],
        "additionalProperties": False,
        "properties": {
            "cards": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
        },
    }


def zone_draft_links_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "major_characters",
            "instances",
            "major_landmarks",
            "glossary",
        ],
        "additionalProperties": False,
        "properties": {
            "major_characters": {"type": "array", "items": LINK_CARD_SCHEMA},
            "instances": {"type": "array", "items": LINK_CARD_SCHEMA},
            "major_landmarks": {"type": "array", "items": LINK_CARD_SCHEMA},
            "glossary": {"type": "array", "items": GLOSSARY_TERM_ID_SCHEMA},
        },
    }
