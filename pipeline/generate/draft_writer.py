"""Draft stage implementation for policy-compliant canonical JSON outputs."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from pipeline.ai.config import load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.common.run_context import RunContext
from pipeline.contracts.models import ENTITY_MODEL_MAP

WORD_RE = re.compile(r"\b[\w']+\b")
SLUG_RE = re.compile(r"[^a-z0-9]+")

INCLUSION_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "inclusion_score",
        "criteria_breakdown",
        "include_decision",
        "decision_reason",
        "source_refs",
    ],
    "additionalProperties": True,
    "properties": {
        "inclusion_score": {"type": "integer", "minimum": 0, "maximum": 12},
        "criteria_breakdown": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"type": "integer", "minimum": 0, "maximum": 2},
        },
        "include_decision": {"type": "string"},
        "decision_reason": {"type": "string", "minLength": 1},
        "source_refs": {"type": "array"},
    },
}

QUESTLINE_CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "title",
        "hook",
        "start_anchor",
        "inclusion_decision",
        "depends_on_parent_context",
    ],
    "additionalProperties": True,
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "faction": {"type": "string"},
        "title": {"type": "string", "minLength": 1},
        "hook": {"type": "string", "minLength": 1},
        "start_anchor": {"type": "string", "minLength": 1},
        "story_beats": {"type": "array", "items": {"type": "string"}},
        "inclusion_decision": INCLUSION_DECISION_SCHEMA,
        "depends_on_parent_context": {"type": "boolean"},
        "dependency_note": {"type": "string"},
    },
}

LINK_CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "name", "summary"],
    "additionalProperties": True,
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "summary": {"type": "string", "minLength": 1},
    },
}


def _slugify(value: str) -> str:
    normalized = SLUG_RE.sub("-", value.lower()).strip("-")
    return normalized or "item"


def _pointer(source_id: str, revision_id: str, locator: str, excerpt_hash: str) -> dict[str, str]:
    return {
        "source_id": source_id,
        "locator": locator,
        "revision_id": revision_id,
        "excerpt_hash": excerpt_hash,
    }


def _word_count(value: str) -> int:
    return len(WORD_RE.findall(value))


def _min_pointers(text: str) -> int:
    words = _word_count(text)
    if words <= 120:
        return 1
    if words <= 240:
        return 2
    return 3


def _pointer_from_fact_item(item: dict[str, Any], *, entity_id: str) -> dict[str, str]:
    fields = ("source_id", "revision_id", "locator", "excerpt_hash")
    values: dict[str, str] = {}
    for field in fields:
        raw_value = item.get(field)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise RuntimeError(
                f"draft provenance for entity '{entity_id}' is missing required "
                f"fact_item field '{field}'"
            )
        values[field] = raw_value.strip()
    return _pointer(
        values["source_id"],
        values["revision_id"],
        values["locator"],
        values["excerpt_hash"],
    )


def _pick_pointers(
    fact_items: list[dict[str, Any]],
    min_count: int,
    *,
    entity_id: str,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    if not fact_items and min_count > 0:
        raise RuntimeError(
            f"draft provenance for entity '{entity_id}' requires source fact_items "
            "but none were provided"
        )
    if not fact_items:
        return output
    for idx in range(max(min_count, 1)):
        item = fact_items[idx % len(fact_items)]
        output.append(_pointer_from_fact_item(item, entity_id=entity_id))
    return output


def _source_entries(fact_pack: dict[str, Any]) -> list[dict[str, str]]:
    source_ids = [str(value) for value in fact_pack["source_ids"]]
    revision_ids = [str(value) for value in fact_pack["revision_ids"]]
    raw_source_urls = fact_pack.get("source_urls", {})
    if not isinstance(raw_source_urls, dict):
        raise RuntimeError("fact pack missing source_urls mapping")
    source_urls = {str(key): str(value) for key, value in raw_source_urls.items()}
    entries: list[dict[str, str]] = []
    for idx in range(min(len(source_ids), len(revision_ids))):
        source_id = source_ids[idx]
        source_url = source_urls.get(source_id, "").strip()
        if not source_url:
            raise RuntimeError(f"fact pack missing source_url for source_id '{source_id}'")
        entries.append(
            {
                "source_id": source_id,
                "url": source_url,
                "revision_id": revision_ids[idx],
            }
        )
    return entries


def _llm_json_with_retry(
    *,
    required_keys: tuple[str, ...],
    response_json_schema: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    max_attempts: int = 3,
    response_schema_name: str = "draft_body",
) -> dict[str, Any]:
    settings = load_ai_settings()
    if not settings.openai_ready:
        raise RuntimeError("draft stage requires OpenAI, but OPENAI_API_KEY is not configured")
    errors: list[str] = []
    schema_validator = Draft202012Validator(response_json_schema)
    for attempt in range(1, max_attempts + 1):
        parsed = chat_json_completion(
            settings,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=settings.openai_model,
            response_json_schema=response_json_schema,
            response_schema_name=response_schema_name,
        )
        if not isinstance(parsed, dict):
            errors.append(f"attempt={attempt}: non-JSON response")
            continue
        schema_errors = list(schema_validator.iter_errors(parsed))
        if schema_errors:
            errors.append(f"attempt={attempt}: schema mismatch {schema_errors[0].message}")
            continue
        missing = [key for key in required_keys if key not in parsed]
        if missing:
            errors.append(f"attempt={attempt}: missing keys {', '.join(missing)}")
            continue
        return parsed
    joined_errors = "; ".join(errors)
    raise RuntimeError(
        f"draft LLM generation failed after {max_attempts} attempts ({joined_errors})"
    )


def _zone_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))

    def _refs_by_id(cards: object, *, key: str = "id") -> dict[str, list[dict[str, str]]]:
        refs: dict[str, list[dict[str, str]]] = {}
        if not isinstance(cards, list):
            return refs
        for card in cards:
            if not isinstance(card, dict):
                continue
            raw_id = card.get(key)
            if isinstance(raw_id, str) and raw_id:
                refs[raw_id] = one_ptr
        return refs

    one_ptr = _pick_pointers(fact_items, 1, entity_id=entity_id)
    alliance_refs = _refs_by_id(draft.get("major_questlines_alliance"))
    horde_refs = _refs_by_id(draft.get("major_questlines_horde"))
    shared_refs = _refs_by_id(draft.get("major_questlines_shared"))
    character_refs = _refs_by_id(draft.get("major_characters"))
    instance_refs = _refs_by_id(draft.get("instances"))
    landmark_refs = _refs_by_id(draft.get("major_landmarks"))
    glossary_refs = _refs_by_id(draft.get("glossary"), key="term_id")
    return {
        "at_a_glance": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["at_a_glance"])),
            entity_id=entity_id,
        ),
        "currently": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["currently"])),
            entity_id=entity_id,
        ),
        "history": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["history"])),
            entity_id=entity_id,
        ),
        "major_questlines_alliance": alliance_refs,
        "major_questlines_horde": horde_refs,
        "major_questlines_shared": shared_refs,
        "major_characters": character_refs,
        "instances": instance_refs,
        "major_landmarks": landmark_refs,
        "glossary": glossary_refs,
    }


def _instance_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    one_ptr = _pick_pointers(fact_items, 1, entity_id=entity_id)
    key_character_refs: dict[str, list[dict[str, str]]] = {}
    raw_key_characters = draft.get("key_characters", [])
    if isinstance(raw_key_characters, list):
        for card in raw_key_characters:
            if not isinstance(card, dict):
                continue
            raw_id = card.get("id")
            if isinstance(raw_id, str) and raw_id:
                key_character_refs[raw_id] = one_ptr
    return {
        "identity_header": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["identity_header"])),
            entity_id=entity_id,
        ),
        "story_context": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["story_context"])),
            entity_id=entity_id,
        ),
        "key_characters": key_character_refs,
    }


def _sub_zone_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    one_ptr = _pick_pointers(fact_items, 1, entity_id=entity_id)

    def _refs_by_id(cards: object, *, key: str = "id") -> dict[str, list[dict[str, str]]]:
        refs: dict[str, list[dict[str, str]]] = {}
        if not isinstance(cards, list):
            return refs
        for card in cards:
            if not isinstance(card, dict):
                continue
            raw_id = card.get(key)
            if isinstance(raw_id, str) and raw_id:
                refs[raw_id] = one_ptr
        return refs

    return {
        "at_a_glance": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["at_a_glance"])),
            entity_id=entity_id,
        ),
        "currently": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["currently"])),
            entity_id=entity_id,
        ),
        "history": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["history"])),
            entity_id=entity_id,
        ),
        "major_questlines_alliance": _refs_by_id(draft.get("major_questlines_alliance")),
        "major_questlines_horde": _refs_by_id(draft.get("major_questlines_horde")),
        "major_questlines_shared": _refs_by_id(draft.get("major_questlines_shared")),
        "major_characters": _refs_by_id(draft.get("major_characters")),
        "instances": _refs_by_id(draft.get("instances")),
        "major_landmarks": _refs_by_id(draft.get("major_landmarks")),
        "glossary": _refs_by_id(draft.get("glossary"), key="term_id"),
    }


def _character_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    return {
        "summary": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["summary"])),
            entity_id=entity_id,
        ),
        "short_history": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["short_history"])),
            entity_id=entity_id,
        ),
    }


def _glossary_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    return {
        "summary": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["summary"])),
            entity_id=entity_id,
        ),
        "brief_history": _pick_pointers(
            fact_items,
            _min_pointers(str(draft["brief_history"])),
            entity_id=entity_id,
        ),
    }


def _asset_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    caption = str(draft.get("caption", "") or "")
    title = str(draft.get("title", ""))
    allowed_use_reason = str(draft.get("allowed_use_reason", ""))
    proof_ref = str(draft.get("proof_ref", ""))
    audit_blob = f"{title}\n{allowed_use_reason}\n{proof_ref}"
    return {
        "caption": (
            _pick_pointers(fact_items, _min_pointers(caption), entity_id=entity_id)
            if caption.strip()
            else []
        ),
        "metadata": _pick_pointers(fact_items, _min_pointers(audit_blob), entity_id=entity_id),
    }


def _zone_draft(fact_pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    claims_text = "\n".join(f"- {claim}" for claim in claims[:12])
    body = _llm_json_with_retry(
        required_keys=(
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
        ),
        response_json_schema={
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
            "additionalProperties": True,
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
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["term_id"],
                        "properties": {"term_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": True,
                    },
                },
            },
        },
        system_prompt=(
            "Create a schema-oriented WoW zone draft body as JSON only. "
            "Use original prose and evidence-backed inclusion decisions."
        ),
        user_prompt=(
            f"Entity: {fact_pack['name']} ({fact_pack['slug']})\n"
            f"Entity id: {fact_pack['entity_id']}\n"
            "Return JSON object with keys: expansion, at_a_glance, currently, history, "
            "major_questlines_alliance, major_questlines_horde, major_questlines_shared, "
            "major_characters, instances, major_landmarks, glossary.\n"
            "Questline cards must include: id, faction, title, hook, start_anchor, "
            "story_beats (<=3), "
            "inclusion_decision with inclusion_score, criteria_breakdown, include_decision, "
            "decision_reason, source_refs (empty list allowed), and depends_on_parent_context.\n"
            f"Claims:\n{claims_text}"
        ),
        response_schema_name="zone_draft_body",
    )
    if not isinstance(body.get("major_questlines_alliance"), list):
        raise RuntimeError("zone draft missing major_questlines_alliance list")
    if not isinstance(body.get("major_questlines_horde"), list):
        raise RuntimeError("zone draft missing major_questlines_horde list")
    if not isinstance(body.get("major_questlines_shared"), list):
        raise RuntimeError("zone draft missing major_questlines_shared list")
    for card in body["major_questlines_alliance"]:
        if isinstance(card, dict):
            card["faction"] = "alliance"
    for card in body["major_questlines_horde"]:
        if isinstance(card, dict):
            card["faction"] = "horde"
    for card in body["major_questlines_shared"]:
        if isinstance(card, dict):
            card["faction"] = "shared"
    draft = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "name": str(fact_pack["name"]),
        "expansion": str(body["expansion"]),
        "at_a_glance": str(body["at_a_glance"]),
        "currently": str(body["currently"]),
        "history": str(body["history"]),
        "major_questlines_alliance": body["major_questlines_alliance"],
        "major_questlines_horde": body["major_questlines_horde"],
        "major_questlines_shared": body["major_questlines_shared"],
        "major_characters": body["major_characters"],
        "instances": body["instances"],
        "major_landmarks": body["major_landmarks"],
        "glossary": body["glossary"],
        "sources": _source_entries(fact_pack),
    }
    draft["provenance"] = _zone_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def _instance_draft(fact_pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    claims_text = "\n".join(f"- {claim}" for claim in claims[:12])
    parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
    if not parent_zone_id:
        raise RuntimeError(
            f"instance draft requires parent_zone_id for entity '{fact_pack['entity_id']}'"
        )
    body = _llm_json_with_retry(
        required_keys=("type", "identity_header", "story_context", "key_characters", "glossary"),
        response_json_schema={
            "type": "object",
            "required": ["type", "identity_header", "story_context", "key_characters", "glossary"],
            "additionalProperties": True,
            "properties": {
                "type": {"type": "string", "minLength": 1},
                "identity_header": {"type": "string", "minLength": 1},
                "story_context": {"type": "string", "minLength": 1},
                "key_characters": {"type": "array", "items": LINK_CARD_SCHEMA},
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["term_id"],
                        "properties": {"term_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": True,
                    },
                },
            },
        },
        system_prompt=(
            "Create a schema-oriented WoW instance draft body as JSON only. "
            "Use original prose and lore-accurate relationships."
        ),
        user_prompt=(
            f"Entity: {fact_pack['name']} ({fact_pack['slug']})\n"
            f"Entity id: {fact_pack['entity_id']}\n"
            f"Parent zone id: {parent_zone_id}\n"
            "Return JSON object with keys: type, identity_header, story_context, "
            "key_characters, glossary.\n"
            f"Claims:\n{claims_text}"
        ),
        response_schema_name="instance_draft_body",
    )
    draft = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "name": str(fact_pack["name"]),
        "type": str(body["type"]),
        "zone_id": parent_zone_id,
        "identity_header": str(body["identity_header"]),
        "story_context": str(body["story_context"]),
        "key_characters": body["key_characters"],
        "zone_backlink": {
            "zone_id": parent_zone_id,
            "label": str(fact_pack.get("parent_zone_label", parent_zone_id)),
        },
        "glossary": body["glossary"],
        "sources": _source_entries(fact_pack),
    }
    draft["provenance"] = _instance_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def _sub_zone_draft(fact_pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    claims_text = "\n".join(f"- {claim}" for claim in claims[:12])
    parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
    if not parent_zone_id:
        raise RuntimeError(
            f"sub-zone draft requires parent_zone_id for entity '{fact_pack['entity_id']}'"
        )
    body = _llm_json_with_retry(
        required_keys=(
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
        ),
        response_json_schema={
            "type": "object",
            "required": [
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
            "additionalProperties": True,
            "properties": {
                "at_a_glance": {"type": "string", "minLength": 1},
                "currently": {"type": "string", "minLength": 1},
                "history": {"type": "string", "minLength": 1},
                "major_questlines_alliance": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
                "major_questlines_horde": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
                "major_questlines_shared": {"type": "array", "items": QUESTLINE_CARD_SCHEMA},
                "major_characters": {"type": "array", "items": LINK_CARD_SCHEMA},
                "instances": {"type": "array", "items": LINK_CARD_SCHEMA},
                "major_landmarks": {"type": "array", "items": LINK_CARD_SCHEMA},
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["term_id"],
                        "properties": {"term_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": True,
                    },
                },
            },
        },
        system_prompt=(
            "Create a schema-oriented WoW sub-zone draft body as JSON only. "
            "Use original prose and lore-accurate relationships."
        ),
        user_prompt=(
            f"Entity: {fact_pack['name']} ({fact_pack['slug']})\n"
            f"Entity id: {fact_pack['entity_id']}\n"
            f"Parent zone id: {parent_zone_id}\n"
            "Return JSON with keys: at_a_glance, currently, history, "
            "major_questlines_alliance, major_questlines_horde, major_questlines_shared, "
            "major_characters, instances, major_landmarks, glossary.\n"
            f"Claims:\n{claims_text}"
        ),
        response_schema_name="sub_zone_draft_body",
    )
    for bucket, faction in (
        ("major_questlines_alliance", "alliance"),
        ("major_questlines_horde", "horde"),
        ("major_questlines_shared", "shared"),
    ):
        cards = body.get(bucket, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"sub-zone draft missing {bucket} list")
        for card in cards:
            if isinstance(card, dict):
                card["faction"] = faction
    draft = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "name": str(fact_pack["name"]),
        "parent_zone_id": parent_zone_id,
        "at_a_glance": str(body["at_a_glance"]),
        "currently": str(body["currently"]),
        "history": str(body["history"]),
        "major_questlines_alliance": body["major_questlines_alliance"],
        "major_questlines_horde": body["major_questlines_horde"],
        "major_questlines_shared": body["major_questlines_shared"],
        "major_characters": body["major_characters"],
        "instances": body["instances"],
        "major_landmarks": body["major_landmarks"],
        "glossary": body["glossary"],
        "sources": _source_entries(fact_pack),
    }
    draft["provenance"] = _sub_zone_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def _character_draft(fact_pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    claims_text = "\n".join(f"- {claim}" for claim in claims[:12])
    body = _llm_json_with_retry(
        required_keys=("summary", "short_history", "glossary"),
        response_json_schema={
            "type": "object",
            "required": ["summary", "short_history", "glossary"],
            "additionalProperties": True,
            "properties": {
                "summary": {"type": "string", "minLength": 1},
                "short_history": {"type": "string", "minLength": 1},
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["term_id"],
                        "properties": {"term_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": True,
                    },
                },
            },
        },
        system_prompt=(
            "Create a schema-oriented WoW character draft body as JSON only. "
            "Use original prose and lore-accurate phrasing."
        ),
        user_prompt=(
            f"Entity: {fact_pack['name']} ({fact_pack['slug']})\n"
            f"Entity id: {fact_pack['entity_id']}\n"
            "Return JSON with keys: summary, short_history, glossary.\n"
            f"Claims:\n{claims_text}"
        ),
        response_schema_name="character_draft_body",
    )
    draft = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "name": str(fact_pack["name"]),
        "summary": str(body["summary"]),
        "short_history": str(body["short_history"]),
        "glossary": body["glossary"],
        "sources": _source_entries(fact_pack),
    }
    draft["provenance"] = _character_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def _glossary_term_draft(fact_pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    claims_text = "\n".join(f"- {claim}" for claim in claims[:12])
    body = _llm_json_with_retry(
        required_keys=("category", "aliases", "summary", "brief_history"),
        response_json_schema={
            "type": "object",
            "required": ["category", "aliases", "summary", "brief_history"],
            "additionalProperties": True,
            "properties": {
                "category": {"type": "string", "minLength": 1},
                "aliases": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "summary": {"type": "string", "minLength": 1},
                "brief_history": {"type": "string", "minLength": 1},
            },
        },
        system_prompt=(
            "Create a schema-oriented WoW glossary term draft body as JSON only. "
            "Use concise and non-promotional prose."
        ),
        user_prompt=(
            f"Entity: {fact_pack['name']} ({fact_pack['slug']})\n"
            f"Entity id: {fact_pack['entity_id']}\n"
            "Return JSON with keys: category, aliases, summary, brief_history.\n"
            "aliases must be lowercase strings.\n"
            f"Claims:\n{claims_text}"
        ),
        response_schema_name="glossary_term_draft_body",
    )
    raw_aliases = body.get("aliases", [])
    aliases = (
        [str(alias).strip().lower() for alias in raw_aliases]
        if isinstance(raw_aliases, list)
        else []
    )
    aliases = [alias for alias in aliases if alias]
    if not aliases:
        aliases = [str(fact_pack["name"]).strip().lower()]
    draft: dict[str, Any] = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "label": str(fact_pack["name"]),
        "category": str(body["category"]),
        "aliases": sorted(set(aliases)),
        "summary": str(body["summary"]),
        "brief_history": str(body["brief_history"]),
        "sources": _source_entries(fact_pack),
    }
    draft["provenance"] = _glossary_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def _asset_draft(fact_pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    claims = [str(claim) for claim in fact_pack.get("claims", [])]
    claims_text = "\n".join(f"- {claim}" for claim in claims[:12])
    first_source = _source_entries(fact_pack)[0]
    body = _llm_json_with_retry(
        required_keys=(
            "asset_type",
            "title",
            "license",
            "credit",
            "allowed_use",
            "allowed_use_reason",
            "proof_ref",
            "associated_entity_ids",
            "caption",
        ),
        response_json_schema={
            "type": "object",
            "required": [
                "asset_type",
                "title",
                "license",
                "credit",
                "allowed_use",
                "allowed_use_reason",
                "proof_ref",
                "associated_entity_ids",
                "caption",
            ],
            "additionalProperties": True,
            "properties": {
                "asset_type": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "license": {"type": "string", "minLength": 1},
                "credit": {"type": "string", "minLength": 1},
                "allowed_use": {"type": "boolean"},
                "allowed_use_reason": {"type": "string", "minLength": 1},
                "proof_ref": {"type": "string", "minLength": 1},
                "associated_entity_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "caption": {"type": "string"},
            },
        },
        system_prompt=(
            "Create a schema-oriented WoW asset metadata draft body as JSON only. "
            "Keep legal/licensing wording factual and concise."
        ),
        user_prompt=(
            f"Entity: {fact_pack['name']} ({fact_pack['slug']})\n"
            f"Entity id: {fact_pack['entity_id']}\n"
            "Return JSON keys: asset_type, title, license, credit, allowed_use, "
            "allowed_use_reason, proof_ref, associated_entity_ids, caption.\n"
            f"Claims:\n{claims_text}"
        ),
        response_schema_name="asset_draft_body",
    )
    allowed_use_value = body.get("allowed_use")
    allowed_use = bool(allowed_use_value) if isinstance(allowed_use_value, bool) else True
    associated_ids_raw = body.get("associated_entity_ids", [])
    associated_ids = (
        [str(value) for value in associated_ids_raw if str(value).strip()]
        if isinstance(associated_ids_raw, list)
        else [str(fact_pack["entity_id"])]
    )
    if not associated_ids:
        associated_ids = [str(fact_pack["entity_id"])]
    draft = {
        "id": str(fact_pack["entity_id"]),
        "asset_type": str(body["asset_type"]),
        "title": str(body["title"]),
        "source_url": first_source["url"],
        "license": str(body["license"]),
        "credit": str(body["credit"]),
        "allowed_use": allowed_use,
        "allowed_use_reason": str(body["allowed_use_reason"]),
        "proof_ref": str(body["proof_ref"]),
        "associated_entity_ids": associated_ids,
        "sources": _source_entries(fact_pack),
        "caption": str(body.get("caption", "")),
    }
    draft["provenance"] = _asset_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def _is_valid_draft(entity_type: str, payload: dict[str, Any]) -> bool:
    model_type = ENTITY_MODEL_MAP[entity_type]
    try:
        model_type.model_validate(payload)
    except Exception:
        return False
    return True


def run_draft_writer(
    context: RunContext,
    fact_pack_paths: list[Path],
    *,
    max_entity_concurrency: int = 4,
) -> list[Path]:
    """Write canonical entity drafts from extracted fact packs."""
    stage_dir = context.data_dir / "drafts"
    stage_dir.mkdir(parents=True, exist_ok=True)

    def _write(path: Path) -> tuple[Path | None, dict[str, object] | None]:
        fact_pack = json.loads(path.read_text(encoding="utf-8"))
        entity_type = str(fact_pack.get("entity_type", ""))
        settings = load_ai_settings()
        generators: dict[str, Any] = {
            "zone": _zone_draft,
            "instance": _instance_draft,
            "sub_zone": _sub_zone_draft,
            "character": _character_draft,
            "glossary_term": _glossary_term_draft,
            "asset": _asset_draft,
        }
        prompt_profiles = {
            "zone": "draft_zone_v1",
            "instance": "draft_instance_v1",
            "sub_zone": "draft_sub_zone_v1",
            "character": "draft_character_v1",
            "glossary_term": "draft_glossary_term_v1",
            "asset": "draft_asset_v1",
        }
        response_schemas = {
            "zone": "zone_draft_body",
            "instance": "instance_draft_body",
            "sub_zone": "sub_zone_draft_body",
            "character": "character_draft_body",
            "glossary_term": "glossary_term_draft_body",
            "asset": "asset_draft_body",
        }
        generator = generators.get(entity_type)
        if generator is None:
            raise RuntimeError(
                f"draft stage does not support entity_type '{entity_type}' for "
                f"entity '{fact_pack.get('entity_id', 'unknown')}'"
            )
        attempts = 3
        mode = "openai"
        draft: dict[str, Any] | None = None
        used_schema_retry = False
        for attempt in range(1, attempts + 1):
            draft, mode = generator(fact_pack)
            if _is_valid_draft(entity_type, draft):
                break
            used_schema_retry = True
            if attempt == attempts:
                raise RuntimeError(
                    f"draft for entity '{fact_pack['entity_id']}' is invalid after "
                    f"{attempts} schema-guarded attempts"
                )
        if draft is None:  # pragma: no cover - defensive guard
            raise RuntimeError(
                f"draft generation returned no payload for '{fact_pack['entity_id']}'"
            )
        entity_dir = stage_dir / entity_type
        entity_dir.mkdir(parents=True, exist_ok=True)
        out_path = entity_dir / f"{draft['id']}.json"
        out_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        return out_path, {
            "entity_id": str(draft["id"]),
            "entity_type": entity_type,
            "generation_mode": mode,
            "coalesce_mode": str(fact_pack.get("coalesce_mode", "unknown")),
            "schema_repair_applied": "yes" if used_schema_retry else "no",
            "ai_provider": getattr(settings, "provider", "openai"),
            "ai_model": settings.openai_model,
            "prompt_profile": prompt_profiles.get(entity_type, "draft_unknown"),
            "response_schema_name": response_schemas.get(entity_type, "draft_body"),
        }

    outputs: list[Path] = []
    decisions: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [executor.submit(_write, path) for path in fact_pack_paths]
        for future in futures:
            output_path, decision = future.result()
            if output_path is not None:
                outputs.append(output_path)
            if decision is not None:
                decisions.append(decision)
    (stage_dir / "draft_decisions.json").write_text(
        json.dumps(decisions, indent=2),
        encoding="utf-8",
    )
    return outputs
