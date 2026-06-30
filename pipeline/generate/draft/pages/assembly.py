"""Shared evidence/pointer/pool primitives for wiki draft page builders."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pipeline.common.content_role import classify_content_role
from pipeline.common.retail import KNOWN_CLASSIC_ENTITIES
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.discovery.entity_typing import normalize_title
from pipeline.discovery.world_registry import entry_kinds
from pipeline.generate.draft.claim_routing import (
    AT_A_GLANCE_ROUTE,
    CURRENTLY_ROUTE,
    FACTION_CONTEXT_ROUTE,
    HISTORY_ROUTE,
    INSTANCE_OVERVIEW_ROUTE,
    LOCATION_CONTEXT_ROUTE,
    item_has_claim_views,
    route_claim_views_for_item,
)
from pipeline.generate.draft.lore_selection import (
    dedupe_lore_items,
    filter_relevant_lore_items,
    is_instance_lore_sparse,
)
from pipeline.generate.draft.temporal import (
    ACTIVE_STORYLINE,
    ACTIVE_STORYLINE_OUTCOME,
    ENTRY_STATE,
    PRE_ENTRY_HISTORY,
    filter_history_items,
    filter_temporal_items,
)

# A major-faction card describes a faction's role in the zone, which for an active belligerent IS
# the current conflict. The entry-state-strict pools (at_a_glance, history, currently) exclude
# active-storyline scopes to keep the stable description from reading like dated patch notes — but
# applying that same exclusion to faction evidence silently starves a seed-only active combatant
# (e.g. the Alliance/Horde contesting Andorhal) of the very evidence that justifies its election, so
# it ranks #1 yet drops with no synthesizable card. Faction pools therefore admit the active-conflict
# scopes in addition to pre-entry / entry-state.
_FACTION_TEMPORAL_SCOPES = frozenset(
    {PRE_ENTRY_HISTORY, ENTRY_STATE, ACTIVE_STORYLINE, ACTIVE_STORYLINE_OUTCOME}
)


def _clean_snippet(text: str) -> str:
    return clean_wiki_snippet(text)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def _source_entries(fact_pack: dict[str, Any]) -> list[dict[str, Any]]:
    source_entries: list[dict[str, Any]] = []
    source_urls = fact_pack.get("source_urls") or {}
    source_ids = fact_pack.get("source_ids") or []
    revision_ids = fact_pack.get("revision_ids") or []
    source_to_revision = {
        str(source_id): str(revision_ids[index])
        for index, source_id in enumerate(source_ids)
        if index < len(revision_ids)
    }
    for source_id, url in source_urls.items():
        if not source_id or not url:
            continue
        source_entries.append(
            {
                "source_id": str(source_id),
                "url": str(url),
                "revision_id": source_to_revision.get(str(source_id)),
            }
        )
    return source_entries


def _iter_evidence_items(
    evidence_rows: list[dict[str, Any]],
    field_names: set[str] | None = None,
    *,
    claim_route: str | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in evidence_rows:
        if field_names is not None and str(row.get("field_name", "")) not in field_names:
            continue
        evidence_items = row.get("evidence_items")
        if not isinstance(evidence_items, list):
            continue
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            if claim_route and item_has_claim_views(item):
                items.extend(route_claim_views_for_item(item, claim_route))
                continue
            snippet = _clean_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            build_meta = row.get("build_meta") or {}
            block_index = item.get("block_index", build_meta.get("block_index", 0))
            try:
                block_index_value = int(block_index)
            except (TypeError, ValueError):
                block_index_value = 0
            out_item = {
                "snippet": snippet,
                "source_url": str(item.get("source_url", "")),
                "source_title": str(item.get("source_title", "")),
                "section_role": str(item.get("section_role", "")),
                "raw_section_role": str(
                    item.get(
                        "raw_section_role",
                        build_meta.get("raw_section_role", item.get("section_role", "")),
                    )
                ),
                "content_role": str(item.get("content_role", build_meta.get("content_role", ""))),
                "block_index": block_index_value,
                "source_id": str(build_meta.get("source_id", "")),
                "field_name": str(row.get("field_name", "")),
                "cluster_id": str(build_meta.get("cluster_id", "")),
                "quest_node_id": str(build_meta.get("quest_node_id", "")),
                "faction_id": str(build_meta.get("faction_id", "")),
                "faction_name": str(build_meta.get("faction_name", "")),
                "location_id": str(build_meta.get("location_id", "")),
                "location_name": str(build_meta.get("location_name", "")),
                "character_id": str(build_meta.get("character_id", "")),
                "character_name": str(build_meta.get("character_name", "")),
                "lore_scope": str(build_meta.get("lore_scope", "")),
                "lore_source_title": str(build_meta.get("lore_source_title", "")),
                "canonical_evidence_id": str(
                    item.get(
                        "canonical_evidence_id",
                        build_meta.get("canonical_evidence_id", ""),
                    )
                ),
                "temporal_scope": str(
                    item.get("temporal_scope", build_meta.get("temporal_scope", ""))
                ),
                "temporal_confidence": item.get(
                    "temporal_confidence", build_meta.get("temporal_confidence")
                ),
                "temporal_reason": str(
                    item.get("temporal_reason", build_meta.get("temporal_reason", ""))
                ),
                "temporal_event_label": str(
                    item.get("temporal_event_label", build_meta.get("temporal_event_label", ""))
                ),
                "history_eligibility": str(
                    item.get("history_eligibility", build_meta.get("history_eligibility", ""))
                ),
                "history_reason": str(
                    item.get("history_reason", build_meta.get("history_reason", ""))
                ),
            }
            claim_views = item.get("_claim_views")
            if isinstance(claim_views, list) and claim_views:
                out_item["_claim_views"] = claim_views
            items.append(out_item)
    return items


def _items_for_source_ids(
    items: list[dict[str, Any]],
    source_ids: list[str],
) -> list[dict[str, Any]]:
    wanted = {source_id for source_id in source_ids if source_id}
    if not wanted:
        return []
    return [item for item in items if str(item.get("source_id", "")) in wanted]


def _pointers_for_source_ids(
    items: list[dict[str, Any]],
    source_ids: list[str],
    revision_map: dict[str, str],
) -> list[dict[str, str]]:
    # Dedupe by excerpt_hash so duplicated evidence rows (a snippet repeated in the
    # pool) can't yield several pointers with the same hash but incrementing locators
    # (RC-6). Locator paragraph numbering runs over the *kept* distinct pointers.
    pointers: list[dict[str, str]] = []
    seen_hashes: set[str] = set()
    index = 1
    for item in _items_for_source_ids(items, source_ids):
        pointer = _pointer_for_item(item, revision_map, index)
        if pointer is None or pointer["excerpt_hash"] in seen_hashes:
            continue
        seen_hashes.add(pointer["excerpt_hash"])
        pointers.append(pointer)
        index += 1
    return pointers


def _pointer_for_item(
    item: dict[str, Any],
    revision_map: dict[str, str],
    locator_index: int,
) -> dict[str, str] | None:
    source_id = str(item.get("source_id", "")).strip()
    snippet = str(item.get("snippet", "")).strip()
    if not source_id or not snippet:
        return None
    revision_id = revision_map.get(source_id)
    if not revision_id:
        return None
    # Provenance locators carry the content_role taxonomy (Option A), not the
    # discovery routing `section_role`. Prefer the value persisted on the
    # evidence item; derive it from the raw header when older evidence predates
    # the field.
    content_role = str(item.get("content_role", "")).strip()
    if not content_role:
        content_role = classify_content_role(
            str(item.get("raw_section_role", "")),
            str(item.get("section_role", "other")),
        )
    hash_text = str(item.get("source_excerpt", "") if item.get("is_claim_view") else snippet).strip()
    if not hash_text:
        hash_text = snippet
    digest = hashlib.sha256(hash_text.encode("utf-8")).hexdigest()[:16]
    return {
        "source_id": source_id,
        "locator": f"section:{content_role} paragraph:{locator_index}",
        "revision_id": revision_id,
        "excerpt_hash": f"sha256:{digest}",
    }


_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})


def _sanitize_cluster_title(cluster_title: str, *, zone_name: str) -> str:
    title = cluster_title.strip() or "Main storylines"
    if entry_kinds(title) & _GEOGRAPHY_KINDS:
        return "Main storylines"
    if zone_name and normalize_title(zone_name) == normalize_title(title):
        return "Main storylines"
    return title


def _cap_card_pointers(
    pointers: list[dict[str, str]],
    max_count: int = 3,
) -> list[dict[str, str]]:
    return pointers[:max_count]


def _pointer_count_for_words(word_count: int) -> int:
    if word_count <= 120:
        return 1
    if word_count <= 240:
        return 2
    return 3


def _ensure_pointer_count(
    pointers: list[dict[str, str]],
    *,
    pool: list[dict[str, Any]],
    revision_map: dict[str, str],
    min_count: int,
) -> list[dict[str, str]]:
    if min_count <= 0 or len(pointers) >= min_count:
        return pointers
    supplemented = list(pointers)
    seen = {(pointer["source_id"], pointer["locator"]) for pointer in supplemented}
    # Also track excerpt_hash so we never supplement with a pointer that repeats an
    # existing excerpt under a fresh locator (RC-6: same-hash/different-locator dupes).
    seen_hashes = {pointer["excerpt_hash"] for pointer in supplemented}
    locator_index = len(supplemented) + 1
    for item in pool:
        if len(supplemented) >= min_count:
            break
        pointer = _pointer_for_item(item, revision_map, locator_index)
        if pointer is None:
            continue
        key = (pointer["source_id"], pointer["locator"])
        if key in seen or pointer["excerpt_hash"] in seen_hashes:
            continue
        supplemented.append(pointer)
        seen.add(key)
        seen_hashes.add(pointer["excerpt_hash"])
        locator_index += 1
    return supplemented


def _attach_history_source_refs(
    sections: list[dict[str, Any]],
    history_pool: list[dict[str, Any]],
    revision_map: dict[str, str],
) -> list[dict[str, Any]]:
    if not sections:
        return sections
    pool = history_pool or []
    updated: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        section_out = dict(section)
        existing_refs = section_out.get("source_refs")
        if isinstance(existing_refs, list) and existing_refs:
            updated.append(section_out)
            continue
        pointer: dict[str, str] | None = None
        if index < len(pool):
            pointer = _pointer_for_item(pool[index], revision_map, index + 1)
        if pointer is None and pool:
            pointer = _pointer_for_item(pool[0], revision_map, index + 1)
        section_out["source_refs"] = [pointer] if pointer else []
        updated.append(section_out)
    return updated


def _history_pointers_from_sections(sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    pointers: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for section in sections:
        if not isinstance(section, dict):
            continue
        refs = section.get("source_refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            source_id = str(ref.get("source_id", "")).strip()
            locator = str(ref.get("locator", "")).strip()
            if not source_id or not locator:
                continue
            key = (source_id, locator)
            if key in seen:
                continue
            seen.add(key)
            pointers.append(ref)
    return pointers


def _normalize_section_role(section_role: str) -> str:
    return re.sub(r"\s+", " ", section_role.strip()).lower().replace(" ", "_")


_GEOGRAPHY_SEED_ROLE_HINTS = ("maps", "subregion", "geography")


def _is_geography_seed_item(item: dict[str, Any]) -> bool:
    role = _normalize_section_role(str(item.get("section_role", "")))
    return any(hint in role for hint in _GEOGRAPHY_SEED_ROLE_HINTS)


def _build_location_seed_pool(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seed_items = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"history_digest", "at_a_glance_input"},
            claim_route=LOCATION_CONTEXT_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE, ACTIVE_STORYLINE},
    )
    for item in seed_items:
        if _is_geography_seed_item(item):
            items.append(item)
    return items


def _build_evidence_pools(evidence_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    history_pool = filter_history_items(
        _iter_evidence_items(evidence_rows, {"history_digest"}, claim_route=HISTORY_ROUTE)
    )
    at_a_glance_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"at_a_glance_input"},
            claim_route=AT_A_GLANCE_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    currently_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"currently_input"},
            claim_route=CURRENTLY_ROUTE,
        ),
        {ENTRY_STATE, PRE_ENTRY_HISTORY, ACTIVE_STORYLINE},
    )
    questline_pool = _iter_evidence_items(evidence_rows, {"questline_pool"})
    quest_cluster_lore_pool = _iter_evidence_items(evidence_rows, {"quest_cluster_lore"})
    quest_lore_pool = _iter_evidence_items(evidence_rows, {"quest_lore"})
    faction_pool = filter_temporal_items(
        _iter_evidence_items(evidence_rows, {"faction_pool"}, claim_route=FACTION_CONTEXT_ROUTE),
        _FACTION_TEMPORAL_SCOPES,
    )
    location_pool = filter_temporal_items(
        _iter_evidence_items(evidence_rows, {"location_pool"}, claim_route=LOCATION_CONTEXT_ROUTE),
        {PRE_ENTRY_HISTORY, ENTRY_STATE, ACTIVE_STORYLINE},
    )
    location_seed_pool = _build_location_seed_pool(evidence_rows)
    instance_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"instances_or_dungeons", "history_digest"},
            claim_route=INSTANCE_OVERVIEW_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    faction_role_pool = _iter_evidence_items(
        evidence_rows,
        {"history_digest", "currently_input", "questline_pool", "at_a_glance_input"},
        claim_route=FACTION_CONTEXT_ROUTE,
    )
    faction_role_pool = filter_temporal_items(
        faction_role_pool,
        _FACTION_TEMPORAL_SCOPES,
    )
    return {
        "at_a_glance_pool": at_a_glance_pool,
        "currently_pool": currently_pool,
        "history_pool": history_pool,
        "faction_role_pool": faction_role_pool,
        "location_pool": location_pool,
        "location_seed_pool": location_seed_pool,
        "instance_pool": instance_pool,
        "questline_pool": questline_pool,
        "quest_cluster_lore_pool": quest_cluster_lore_pool,
        "quest_lore_pool": quest_lore_pool,
        "faction_pool": faction_pool,
    }


def _build_zone_mention_pool(
    instance_name: str,
    parent_zone_evidence_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not instance_name.strip() or not parent_zone_evidence_rows:
        return []
    pattern = re.compile(rf"\b{re.escape(instance_name.strip())}\b", re.IGNORECASE)
    items: list[dict[str, Any]] = []
    parent_items = filter_temporal_items(
        _iter_evidence_items(
            parent_zone_evidence_rows,
            {"history_digest", "at_a_glance_input", "currently_input", "instances_or_dungeons"},
            claim_route=INSTANCE_OVERVIEW_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    for item in parent_items:
        if pattern.search(str(item.get("snippet", ""))):
            items.append(item)
    return items


def _build_instance_evidence_pools(
    evidence_rows: list[dict[str, Any]],
    *,
    instance_name: str = "",
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    history_pool = filter_history_items(
        _iter_evidence_items(evidence_rows, {"history_digest"}, claim_route=HISTORY_ROUTE)
    )
    at_a_glance_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"at_a_glance_input"},
            claim_route=AT_A_GLANCE_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    boss_pool = filter_temporal_items(
        _iter_evidence_items(evidence_rows, {"boss_pool"}),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    instance_lore_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"instance_lore_pool"},
            claim_route=INSTANCE_OVERVIEW_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    parent_lore_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"parent_lore_pool"},
            claim_route=INSTANCE_OVERVIEW_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    related_lore_pool = filter_temporal_items(
        _iter_evidence_items(
            evidence_rows,
            {"related_lore_pool"},
            claim_route=INSTANCE_OVERVIEW_ROUTE,
        ),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    # Slice I4: the instance's own narrative is primary. Cross-page (parent-complex /
    # related) lore only augments the overview when the instance page is sparse, and
    # only snippets that explicitly name the instance are fused (attribution guard).
    # Rich instances keep their exact prior overview pool, so output never regresses.
    instance_own_overview = history_pool + instance_lore_pool
    instance_lore_sparse = is_instance_lore_sparse(instance_own_overview)
    if instance_lore_sparse:
        cross_relevant = filter_relevant_lore_items(
            related_lore_pool + parent_lore_pool, instance_name=instance_name
        )
        overview_pool = dedupe_lore_items(instance_own_overview + cross_relevant)
    else:
        overview_pool = instance_own_overview
    zone_mention_pool = _build_zone_mention_pool(instance_name, parent_zone_evidence_rows or [])
    faction_pool = filter_temporal_items(
        _iter_evidence_items(evidence_rows, {"faction_pool"}, claim_route=FACTION_CONTEXT_ROUTE),
        _FACTION_TEMPORAL_SCOPES,
    )
    faction_role_pool = _iter_evidence_items(
        evidence_rows,
        {"history_digest", "instance_lore_pool", "at_a_glance_input", "boss_pool"},
        claim_route=FACTION_CONTEXT_ROUTE,
    )
    faction_role_pool = filter_temporal_items(
        faction_role_pool,
        _FACTION_TEMPORAL_SCOPES,
    )
    # Slice D: per-character biography from the crawled character pages. Built raw like boss_pool
    # (the key-character finalizer applies KEY_CHARACTER_ROUTE itself, dropping spoiler-unsafe
    # views); bounded to pre-entry/entry-state here, then merged into each candidate's profile_pool
    # so summaries carry real biographical substance instead of a structural-presence template.
    character_pool = filter_temporal_items(
        _iter_evidence_items(evidence_rows, {"character_pool"}),
        {PRE_ENTRY_HISTORY, ENTRY_STATE},
    )
    return {
        "at_a_glance_pool": at_a_glance_pool,
        "history_pool": history_pool,
        "overview_pool": overview_pool,
        "boss_pool": boss_pool,
        "character_pool": character_pool,
        "instance_lore_pool": instance_lore_pool,
        "parent_lore_pool": parent_lore_pool,
        "related_lore_pool": related_lore_pool,
        "instance_lore_sparse": instance_lore_sparse,
        "zone_mention_pool": zone_mention_pool,
        "faction_pool": faction_pool,
        "faction_role_pool": faction_role_pool,
    }


def _extract_instance_structured_links(
    snapshots: list[dict[str, Any]] | None, instance_id: str
) -> list[dict[str, Any]]:
    if not snapshots:
        return []
    for snapshot in snapshots:
        if (
            str(snapshot.get("entity_id", "")).strip() == instance_id
            and str(snapshot.get("entity_type", "")).strip() == "instance"
            and not str(snapshot.get("auxiliary_role", "")).strip()
        ):
            raw_links = snapshot.get("structured_links", [])
            if isinstance(raw_links, list):
                return [row for row in raw_links if isinstance(row, dict)]
            break
    return []


def _classic_excluded_names(snapshots: list[dict[str, Any]] | None, instance_id: str) -> set[str]:
    """S3 retail/Classic cast exclusion set (normalized names).

    Union of the known-Classic backstop denylist and the instance snapshot's
    ``classic_excluded_characters`` (the authoritative wiki-category exclusions captured
    during traverse). Names are normalized to match ``prefilter_character_pool``.
    """
    excluded = {normalize_title(name) for name in KNOWN_CLASSIC_ENTITIES}
    for snapshot in snapshots or []:
        if (
            str(snapshot.get("entity_id", "")).strip() == instance_id
            and str(snapshot.get("entity_type", "")).strip() == "instance"
            and not str(snapshot.get("auxiliary_role", "")).strip()
        ):
            names = snapshot.get("classic_excluded_characters", [])
            if isinstance(names, list):
                excluded.update(normalize_title(str(name)) for name in names)
            break
    return excluded
