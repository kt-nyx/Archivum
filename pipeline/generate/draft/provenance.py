"""Provenance pointer assembly for canonical drafts."""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft.common import min_pointers, pick_pointers


def zone_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    one_ptr = pick_pointers(fact_items, 1, entity_id=entity_id)

    def refs_by_id(cards: object, *, key: str = "id") -> dict[str, list[dict[str, str]]]:
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
        "at_a_glance": pick_pointers(
            fact_items, min_pointers(str(draft["at_a_glance"])), entity_id=entity_id
        ),
        "currently": pick_pointers(
            fact_items, min_pointers(str(draft["currently"])), entity_id=entity_id
        ),
        "history": pick_pointers(
            fact_items, min_pointers(str(draft["history"])), entity_id=entity_id
        ),
        "major_questlines_alliance": refs_by_id(draft.get("major_questlines_alliance")),
        "major_questlines_horde": refs_by_id(draft.get("major_questlines_horde")),
        "major_questlines_shared": refs_by_id(draft.get("major_questlines_shared")),
        "major_characters": refs_by_id(draft.get("major_characters")),
        "instances": refs_by_id(draft.get("instances")),
        "major_landmarks": refs_by_id(draft.get("major_landmarks")),
        "glossary": refs_by_id(draft.get("glossary"), key="term_id"),
    }


def sub_zone_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    return zone_provenance(fact_items=fact_items, draft=draft)


def instance_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    one_ptr = pick_pointers(fact_items, 1, entity_id=entity_id)
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
        "identity_header": pick_pointers(
            fact_items, min_pointers(str(draft["identity_header"])), entity_id=entity_id
        ),
        "story_context": pick_pointers(
            fact_items, min_pointers(str(draft["story_context"])), entity_id=entity_id
        ),
        "key_characters": key_character_refs,
    }


def character_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    return {
        "summary": pick_pointers(
            fact_items, min_pointers(str(draft["summary"])), entity_id=entity_id
        ),
        "short_history": pick_pointers(
            fact_items, min_pointers(str(draft["short_history"])), entity_id=entity_id
        ),
    }


def glossary_provenance(
    *,
    fact_items: list[dict[str, Any]],
    draft: dict[str, Any],
) -> dict[str, Any]:
    entity_id = str(draft.get("id", "unknown-entity"))
    return {
        "summary": pick_pointers(
            fact_items, min_pointers(str(draft["summary"])), entity_id=entity_id
        ),
        "brief_history": pick_pointers(
            fact_items, min_pointers(str(draft["brief_history"])), entity_id=entity_id
        ),
    }


def asset_provenance(
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
            pick_pointers(fact_items, min_pointers(caption), entity_id=entity_id)
            if caption.strip()
            else []
        ),
        "metadata": pick_pointers(fact_items, min_pointers(audit_blob), entity_id=entity_id),
    }
