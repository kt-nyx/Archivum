"""Single-call draft generators (legacy monolithic path)."""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft.common import (
    assign_questline_factions,
    claims_text,
    entity_header,
    normalize_questline_criteria_breakdowns,
    source_entries,
)
from pipeline.generate.draft.limits import apply_body_caps, cap_prompt_hint, load_draft_limits
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.provenance import (
    asset_provenance,
    character_provenance,
    glossary_provenance,
    instance_provenance,
    sub_zone_provenance,
    zone_provenance,
)
from pipeline.generate.draft.schemas import (
    LINK_CARD_SCHEMA,
    sub_zone_draft_body_schema,
    zone_draft_body_schema,
)
from pipeline.generate.draft.trace import DraftTraceContext


def zone_draft(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    limits = load_draft_limits()
    body = llm_json_with_retry(
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
        response_json_schema=zone_draft_body_schema(),
        system_prompt=(
            "Produce a WoW zone draft as JSON only. Use original prose and "
            "evidence-backed inclusion decisions for questline cards."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"{cap_prompt_hint(limits)}\n"
            f"Claims:\n{claims_text(fact_pack)}"
        ),
        response_schema_name="zone_draft_body",
        trace=trace,
        substep="legacy_zone_body",
    )
    apply_body_caps(body, limits)
    normalize_questline_criteria_breakdowns(body)
    assign_questline_factions(body)
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
        "sources": source_entries(fact_pack),
    }
    draft["provenance"] = zone_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def sub_zone_draft(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
    if not parent_zone_id:
        raise RuntimeError(
            f"sub-zone draft requires parent_zone_id for entity '{fact_pack['entity_id']}'"
        )
    limits = load_draft_limits()
    body = llm_json_with_retry(
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
        response_json_schema=sub_zone_draft_body_schema(),
        system_prompt=(
            "Produce a WoW sub-zone draft as JSON only. Use original prose and "
            "lore-accurate relationships."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"Parent zone id: {parent_zone_id}\n"
            f"{cap_prompt_hint(limits)}\n"
            f"Claims:\n{claims_text(fact_pack)}"
        ),
        response_schema_name="sub_zone_draft_body",
        trace=trace,
        substep="legacy_sub_zone_body",
    )
    apply_body_caps(body, limits)
    normalize_questline_criteria_breakdowns(body)
    assign_questline_factions(body)
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
        "sources": source_entries(fact_pack),
    }
    draft["provenance"] = sub_zone_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def instance_draft(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
    if not parent_zone_id:
        raise RuntimeError(
            f"instance draft requires parent_zone_id for entity '{fact_pack['entity_id']}'"
        )
    body = llm_json_with_retry(
        required_keys=("type", "identity_header", "story_context", "key_characters", "glossary"),
        response_json_schema={
            "type": "object",
            "required": ["type", "identity_header", "story_context", "key_characters", "glossary"],
            "additionalProperties": False,
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
                        "additionalProperties": False,
                    },
                },
            },
        },
        system_prompt=(
            "Produce a WoW instance draft as JSON only. Use original prose and "
            "lore-accurate relationships."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            f"Parent zone id: {parent_zone_id}\n"
            f"Claims:\n{claims_text(fact_pack)}"
        ),
        response_schema_name="instance_draft_body",
        trace=trace,
        substep="legacy_instance_body",
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
        "sources": source_entries(fact_pack),
    }
    draft["provenance"] = instance_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def character_draft(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    body = llm_json_with_retry(
        required_keys=("summary", "short_history", "glossary"),
        response_json_schema={
            "type": "object",
            "required": ["summary", "short_history", "glossary"],
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string", "minLength": 1},
                "short_history": {"type": "string", "minLength": 1},
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["term_id"],
                        "properties": {"term_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": False,
                    },
                },
            },
        },
        system_prompt=("Produce a WoW character draft as JSON only. Use original prose."),
        user_prompt=f"{entity_header(fact_pack)}Claims:\n{claims_text(fact_pack)}",
        response_schema_name="character_draft_body",
        trace=trace,
        substep="legacy_character_body",
    )
    draft = {
        "id": str(fact_pack["entity_id"]),
        "slug": str(fact_pack["slug"]),
        "name": str(fact_pack["name"]),
        "summary": str(body["summary"]),
        "short_history": str(body["short_history"]),
        "glossary": body["glossary"],
        "sources": source_entries(fact_pack),
    }
    draft["provenance"] = character_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def glossary_term_draft(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    body = llm_json_with_retry(
        required_keys=("category", "aliases", "summary", "brief_history"),
        response_json_schema={
            "type": "object",
            "required": ["category", "aliases", "summary", "brief_history"],
            "additionalProperties": False,
            "properties": {
                "category": {"type": "string", "minLength": 1},
                "aliases": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "summary": {"type": "string", "minLength": 1},
                "brief_history": {"type": "string", "minLength": 1},
            },
        },
        system_prompt=(
            "Produce a WoW glossary term draft as JSON only. Use concise non-promotional prose."
        ),
        user_prompt=(
            f"{entity_header(fact_pack)}"
            "aliases must be lowercase strings.\n"
            f"Claims:\n{claims_text(fact_pack)}"
        ),
        response_schema_name="glossary_term_draft_body",
        trace=trace,
        substep="legacy_glossary_term_body",
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
        "sources": source_entries(fact_pack),
    }
    draft["provenance"] = glossary_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"


def asset_draft(
    fact_pack: dict[str, Any],
    *,
    trace: DraftTraceContext | None = None,
) -> tuple[dict[str, Any], str]:
    fact_items = [item for item in fact_pack.get("fact_items", []) if isinstance(item, dict)]
    first_source = source_entries(fact_pack)[0]
    body = llm_json_with_retry(
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
            "additionalProperties": False,
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
        system_prompt=("Produce WoW asset metadata as JSON only. Keep licensing wording factual."),
        user_prompt=f"{entity_header(fact_pack)}Claims:\n{claims_text(fact_pack)}",
        response_schema_name="asset_draft_body",
        trace=trace,
        substep="legacy_asset_body",
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
        "sources": source_entries(fact_pack),
        "caption": str(body.get("caption", "")),
    }
    draft["provenance"] = asset_provenance(fact_items=fact_items, draft=draft)
    return draft, "openai"
