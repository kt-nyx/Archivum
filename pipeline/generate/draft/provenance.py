"""Provenance pointer assembly for canonical drafts."""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft.common import min_pointers, pick_pointers


def build_revision_index(
    fact_pack: dict[str, Any],
    snapshots: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Merge coalesce fact_pack revisions with ingest snapshot rows (snapshots win)."""
    revision_map: dict[str, str] = {}
    source_urls: dict[str, str] = {}

    source_ids = fact_pack.get("source_ids") or []
    revision_ids = fact_pack.get("revision_ids") or []
    if isinstance(source_ids, list) and isinstance(revision_ids, list):
        for index, source_id in enumerate(source_ids):
            sid = str(source_id).strip()
            if not sid or index >= len(revision_ids):
                continue
            revision_id = str(revision_ids[index]).strip()
            if revision_id:
                revision_map[sid] = revision_id

    for snapshot in snapshots or []:
        if not isinstance(snapshot, dict):
            continue
        sid = str(snapshot.get("source_id", "")).strip()
        if not sid:
            continue
        snapshot_revision = snapshot.get("revision_id")
        if snapshot_revision:
            revision_map[sid] = str(snapshot_revision)
        url = snapshot.get("url")
        if url:
            source_urls[sid] = str(url)

    fact_urls = fact_pack.get("source_urls") or {}
    if isinstance(fact_urls, dict):
        for source_id, url in fact_urls.items():
            sid = str(source_id).strip()
            if sid and url and sid not in source_urls:
                source_urls[sid] = str(url)

    return revision_map, source_urls


def _collect_pointer_source_ids(pointers: object, source_ids: set[str]) -> None:
    if isinstance(pointers, list):
        for row in pointers:
            if isinstance(row, dict):
                source_id = str(row.get("source_id", "")).strip()
                if source_id:
                    source_ids.add(source_id)
    elif isinstance(pointers, dict):
        for card_pointers in pointers.values():
            _collect_pointer_source_ids(card_pointers, source_ids)


def collect_sources_manifest(
    page_entity: dict[str, Any],
    revision_map: dict[str, str],
    source_urls: dict[str, str],
) -> list[dict[str, Any]]:
    """Build sources[] from every provenance pointer referenced on the page."""
    source_ids: set[str] = set()
    provenance = page_entity.get("provenance")
    if isinstance(provenance, dict):
        for value in provenance.values():
            _collect_pointer_source_ids(value, source_ids)

    history_sections = page_entity.get("history_sections")
    if isinstance(history_sections, list):
        for section in history_sections:
            if isinstance(section, dict):
                _collect_pointer_source_ids(section.get("source_refs"), source_ids)

    entries: list[dict[str, Any]] = []
    for source_id in sorted(source_ids):
        url = source_urls.get(source_id)
        if not url:
            continue
        entries.append(
            {
                "source_id": source_id,
                "url": url,
                "revision_id": revision_map.get(source_id),
            }
        )
    return entries


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
