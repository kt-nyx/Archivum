"""Wiki-first draft builders that consume deterministic evidence packs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.generate.draft.instance_link_lint import trim_instance_link_summary
from pipeline.generate.draft.instance_lint import (
    fallback_instance_overview,
    fallback_key_character_summary,
    lint_at_a_glance as lint_instance_at_a_glance,
    lint_key_character_summary,
    lint_overview,
    lint_passthrough_fragment,
)
from pipeline.discovery.entity_typing import normalize_title
from pipeline.discovery.geography import resolve_parent_continent
from pipeline.discovery.instance_bosses import (
    BossCandidate,
    cap_pool_for_llm_prompt,
    collect_character_pool,
    deterministic_pool_order,
    merge_key_character_cast,
    merged_cast_candidates,
    must_include_key_character_names,
    prefilter_character_pool,
)
from pipeline.discovery.world_registry import entry_kinds
from pipeline.contracts.models import INSTANCE_MAX_KEY_CHARACTERS, ZONE_MAX_TOTAL_QUESTLINE_CARDS
from pipeline.generate.draft.faction_lint import ensure_sentence_terminator, lint_faction_summary
from pipeline.generate.draft.faction_scoring import (
    FactionCandidate,
    MAX_FACTION_CARDS,
    candidates_for_finalize,
    collect_faction_candidates,
    fallback_faction_summary,
    finalize_evidence_pools,
)
from pipeline.generate.draft.location_lint import (
    ensure_sentence_terminator as ensure_location_sentence_terminator,
    lint_location_summary,
)
from pipeline.generate.draft.location_scoring import (
    LocationCandidate,
    MAX_LOCATION_CARDS,
    _decision_reason_codes,
    candidates_for_finalize as location_candidates_for_finalize,
    collect_location_candidates,
    extract_subregion_tokens,
    finalize_evidence_pools as finalize_location_evidence_pools,
)
from pipeline.generate.draft.location_lint import fallback_location_summary
from pipeline.common.wiki_evidence_filters import cap_history_pool
from pipeline.generate.draft.prose_election import (
    fallback_at_a_glance,
    fallback_currently,
    fallback_history_sections,
    history_section_cap,
    select_at_a_glance_pool,
    select_currently_pool,
    select_history_pool,
)
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    MAX_HISTORY_SECTIONS,
    MIN_HISTORY_SECTIONS,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
)
from pipeline.generate.draft.card_lint import finalize_cta_hook, lint_cta_hook, strip_zone_name_from_cta
from pipeline.generate.draft.lore_selection import (
    build_sparse_lore_rescue_pool,
    dedupe_lore_items,
    filter_relevant_lore_items,
    is_instance_lore_sparse,
)
from pipeline.generate.draft.provenance import build_revision_index, collect_sources_manifest
from pipeline.generate.draft.wiki_first_workers import (
    classify_key_character_role_llm,
    synthesize_at_a_glance,
    synthesize_card_summary,
    synthesize_questline_cta_hook,
    synthesize_currently,
    synthesize_faction_summary,
    synthesize_history_sections,
    synthesize_instance_overview,
    synthesize_key_character_summary,
    synthesize_location_summary,
    select_key_characters_from_pool,
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
            snippet = _clean_snippet(str(item.get("snippet", "")))
            if not snippet:
                continue
            build_meta = row.get("build_meta") or {}
            block_index = item.get("block_index", build_meta.get("block_index", 0))
            try:
                block_index_value = int(block_index)
            except (TypeError, ValueError):
                block_index_value = 0
            items.append(
                {
                    "snippet": snippet,
                    "source_url": str(item.get("source_url", "")),
                    "source_title": str(item.get("source_title", "")),
                    "section_role": str(item.get("section_role", "")),
                    "raw_section_role": str(
                        item.get("raw_section_role", build_meta.get("raw_section_role", item.get("section_role", "")))
                    ),
                    "block_index": block_index_value,
                    "source_id": str(build_meta.get("source_id", "")),
                    "field_name": str(row.get("field_name", "")),
                    "cluster_id": str(build_meta.get("cluster_id", "")),
                    "quest_node_id": str(build_meta.get("quest_node_id", "")),
                    "faction_id": str(build_meta.get("faction_id", "")),
                    "faction_name": str(build_meta.get("faction_name", "")),
                    "location_id": str(build_meta.get("location_id", "")),
                    "location_name": str(build_meta.get("location_name", "")),
                    "lore_scope": str(build_meta.get("lore_scope", "")),
                    "lore_source_title": str(build_meta.get("lore_source_title", "")),
                }
            )
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
    pointers: list[dict[str, str]] = []
    for index, item in enumerate(_items_for_source_ids(items, source_ids), start=1):
        pointer = _pointer_for_item(item, revision_map, index)
        if pointer:
            pointers.append(pointer)
    return pointers


def _pointer_for_item(
    item: dict[str, Any],
    revision_map: dict[str, str],
    locator_index: int,
) -> dict[str, str] | None:
    source_id = str(item.get("source_id", "")).strip()
    snippet = str(item.get("snippet", "")).strip()
    section_role = str(item.get("section_role", "other")).strip() or "other"
    if not source_id or not snippet:
        return None
    revision_id = revision_map.get(source_id)
    if not revision_id:
        return None
    digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]
    return {
        "source_id": source_id,
        "locator": f"section:{section_role} paragraph:{locator_index}",
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
    locator_index = len(supplemented) + 1
    for item in pool:
        if len(supplemented) >= min_count:
            break
        pointer = _pointer_for_item(item, revision_map, locator_index)
        if pointer is None:
            continue
        key = (pointer["source_id"], pointer["locator"])
        if key in seen:
            continue
        supplemented.append(pointer)
        seen.add(key)
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
    for item in _iter_evidence_items(evidence_rows, {"history_digest", "at_a_glance_input"}):
        if _is_geography_seed_item(item):
            items.append(item)
    return items


def _build_evidence_pools(evidence_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    history_pool = _iter_evidence_items(evidence_rows, {"history_digest"})
    at_a_glance_pool = _iter_evidence_items(evidence_rows, {"at_a_glance_input"})
    currently_pool = _iter_evidence_items(evidence_rows, {"currently_input"})
    questline_pool = _iter_evidence_items(evidence_rows, {"questline_pool"})
    quest_cluster_lore_pool = _iter_evidence_items(evidence_rows, {"quest_cluster_lore"})
    quest_lore_pool = _iter_evidence_items(evidence_rows, {"quest_lore"})
    faction_pool = _iter_evidence_items(evidence_rows, {"faction_pool"})
    location_pool = _iter_evidence_items(evidence_rows, {"location_pool"})
    location_seed_pool = _build_location_seed_pool(evidence_rows)
    instance_pool = _iter_evidence_items(evidence_rows, {"instances_or_dungeons", "history_digest"})
    faction_role_pool = _iter_evidence_items(
        evidence_rows, {"history_digest", "currently_input", "questline_pool", "at_a_glance_input"}
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
    for item in _iter_evidence_items(
        parent_zone_evidence_rows,
        {"history_digest", "at_a_glance_input", "currently_input", "instances_or_dungeons"},
    ):
        if pattern.search(str(item.get("snippet", ""))):
            items.append(item)
    return items


def _build_instance_evidence_pools(
    evidence_rows: list[dict[str, Any]],
    *,
    instance_name: str = "",
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    history_pool = _iter_evidence_items(evidence_rows, {"history_digest"})
    at_a_glance_pool = _iter_evidence_items(evidence_rows, {"at_a_glance_input"})
    boss_pool = _iter_evidence_items(evidence_rows, {"boss_pool"})
    instance_lore_pool = _iter_evidence_items(evidence_rows, {"instance_lore_pool"})
    parent_lore_pool = _iter_evidence_items(evidence_rows, {"parent_lore_pool"})
    related_lore_pool = _iter_evidence_items(evidence_rows, {"related_lore_pool"})
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
    faction_pool = _iter_evidence_items(evidence_rows, {"faction_pool"})
    faction_role_pool = _iter_evidence_items(
        evidence_rows,
        {"history_digest", "instance_lore_pool", "at_a_glance_input", "boss_pool"},
    )
    return {
        "at_a_glance_pool": at_a_glance_pool,
        "history_pool": history_pool,
        "overview_pool": overview_pool,
        "boss_pool": boss_pool,
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


_POOL_SELECTION_CONTEXT_MAX_CHARS = 800


@dataclass
class InstanceKeyCharacterSelection:
    """Option F cast selection: merged emit list + full prefiltered pool for sidecar."""

    cast: list[BossCandidate] = field(default_factory=list)
    pool: list[BossCandidate] = field(default_factory=list)
    selection_reasons: dict[str, str] = field(default_factory=dict)
    context_text: str = ""


def _instance_key_character_context_text(pools: dict[str, list[dict[str, Any]]]) -> str:
    parts: list[str] = []
    for item in pools.get("overview_pool", []) + pools.get("at_a_glance_pool", []):
        snippet = clean_wiki_snippet(str(item.get("snippet", "")))
        if snippet:
            parts.append(snippet)
    combined = " ".join(parts).strip()
    return combined[:_POOL_SELECTION_CONTEXT_MAX_CHARS]


def _order_sidecar_pool_candidates(
    pool: list[BossCandidate],
    *,
    cast_names: list[str],
    context_text: str,
) -> list[BossCandidate]:
    """Emitted cast first (merge order), then non-emitted by offline rank (diversity window)."""
    pool_by_name = {candidate.name: candidate for candidate in pool}
    cast_keys = {normalize_title(name) for name in cast_names}
    ordered: list[BossCandidate] = []
    seen: set[str] = set()
    for name in cast_names:
        candidate = pool_by_name.get(name)
        if candidate is None:
            continue
        key = normalize_title(candidate.name)
        if key in seen:
            continue
        ordered.append(candidate)
        seen.add(key)
    remaining = [candidate for candidate in pool if normalize_title(candidate.name) not in cast_keys]
    for name in deterministic_pool_order(remaining, narrative_text=context_text):
        candidate = pool_by_name.get(name)
        if candidate is None:
            continue
        key = normalize_title(candidate.name)
        if key in seen:
            continue
        ordered.append(candidate)
        seen.add(key)
    return ordered


def build_instance_key_character_selection(
    *,
    instance_id: str,
    instance_name: str,
    evidence_rows: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    pools: dict[str, list[dict[str, Any]]] | None = None,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> InstanceKeyCharacterSelection:
    """Option F: pool → prefilter → floor → LLM → merge."""
    if pools is None:
        pools = _build_instance_evidence_pools(
            evidence_rows,
            instance_name=instance_name,
            parent_zone_evidence_rows=parent_zone_evidence_rows,
        )
    blocks = section_blocks if isinstance(section_blocks, list) else []
    structured_links = _extract_instance_structured_links(snapshots, instance_id)
    narrative_pool = pools["overview_pool"] + pools["at_a_glance_pool"]
    history_pool = pools.get("history_pool", [])
    context_text = _instance_key_character_context_text(pools)

    raw_pool = collect_character_pool(
        section_blocks=blocks,
        instance_name=instance_name,
        boss_pool_items=pools["boss_pool"],
        structured_links=structured_links,
        narrative_pool=narrative_pool,
        history_pool=history_pool,
    )
    pool = prefilter_character_pool(raw_pool, instance_name=instance_name)
    if not pool:
        return InstanceKeyCharacterSelection(context_text=context_text)

    floor = must_include_key_character_names(
        boss_pool_items=pools["boss_pool"],
        pool=pool,
        instance_name=instance_name,
    )
    if len(floor) > INSTANCE_MAX_KEY_CHARACTERS:
        floor = floor[:INSTANCE_MAX_KEY_CHARACTERS]

    llm_names: list[str] = []
    remaining = INSTANCE_MAX_KEY_CHARACTERS - len(floor)
    if remaining > 0:
        prompt_pool = cap_pool_for_llm_prompt(
            pool,
            must_include_names=floor,
            limit=40,
        )
        llm_names = select_key_characters_from_pool(
            prompt_pool,
            instance_name=instance_name,
            context_text=context_text,
            max_count=remaining,
            exclude_names=floor,
        )

    merged_names, selection_reasons = merge_key_character_cast(
        pool,
        must_include_names=floor,
        llm_ordered_names=llm_names,
        max_count=INSTANCE_MAX_KEY_CHARACTERS,
    )
    cast = merged_cast_candidates(pool, merged_names, instance_name=instance_name)
    sidecar_pool = _order_sidecar_pool_candidates(
        pool,
        cast_names=merged_names,
        context_text=context_text,
    )
    return InstanceKeyCharacterSelection(
        cast=cast,
        pool=sidecar_pool,
        selection_reasons=selection_reasons,
        context_text=context_text,
    )


def build_instance_key_character_roster(
    *,
    instance_id: str,
    instance_name: str,
    evidence_rows: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    pools: dict[str, list[dict[str, Any]]] | None = None,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> list[BossCandidate]:
    """Merged cast order for page assembly (Option F)."""
    return build_instance_key_character_selection(
        instance_id=instance_id,
        instance_name=instance_name,
        evidence_rows=evidence_rows,
        section_blocks=section_blocks,
        snapshots=snapshots,
        pools=pools,
        parent_zone_evidence_rows=parent_zone_evidence_rows,
    ).cast


def _finalize_instance_at_a_glance(
    *,
    instance_name: str,
    at_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    text, used = synthesize_at_a_glance(
        at_pool, max_words=MAX_AT_A_GLANCE_WORDS, subject=instance_name
    )
    producing_pool = at_pool
    if lint_instance_at_a_glance(text, instance_name=instance_name):
        text, used = fallback_at_a_glance(at_pool)
        if lint_instance_at_a_glance(text, instance_name=instance_name):
            text, used = "", []
    if not text:
        rescue_pool = at_pool or select_at_a_glance_pool(
            _iter_evidence_items(evidence_rows, {"at_a_glance_input", "history_digest"})
        )
        producing_pool = rescue_pool
        text, used = fallback_at_a_glance(rescue_pool)
        if lint_instance_at_a_glance(text, instance_name=instance_name):
            text, used = "", []
            producing_pool = []
    return text, used, producing_pool


def _finalize_instance_overview(
    *,
    instance_name: str,
    overview_pool: list[dict[str, Any]],
    zone_mention_pool: list[dict[str, Any]],
    sparse_rescue_pool: list[dict[str, Any]] | None = None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    pools_to_try: list[list[dict[str, Any]]] = []
    if overview_pool:
        pools_to_try.append(overview_pool)
    if zone_mention_pool:
        rescue_pool = overview_pool + zone_mention_pool
        if rescue_pool not in pools_to_try:
            pools_to_try.append(rescue_pool)
    # Slice I4 last resort: a genuinely sparse instance whose own page (and any
    # instance-naming cross-page lore) produced nothing falls back to parent-complex
    # context here. This runs only after the instance-first pools above are exhausted.
    if sparse_rescue_pool:
        combined = overview_pool + sparse_rescue_pool
        if combined not in pools_to_try:
            pools_to_try.append(combined)

    for pool in pools_to_try:
        text, used = synthesize_instance_overview(pool, instance_name=instance_name)
        if not lint_overview(text, instance_name=instance_name) and not lint_passthrough_fragment(text):
            return text, used, pool
        text, used = fallback_instance_overview(pool, instance_name=instance_name)
        if not lint_overview(text, instance_name=instance_name) and not lint_passthrough_fragment(text):
            return text, used, pool
    return "", [], []


def _finalize_key_characters(
    *,
    instance_name: str,
    boss_candidates: list[BossCandidate],
    boss_pool: list[dict[str, Any]],
    revision_map: dict[str, str],
    selection_reasons: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]], set[str]]:
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    used_source_ids: set[str] = set()
    if not boss_candidates:
        return cards, provenance_map, used_source_ids

    for candidate in boss_candidates[:INSTANCE_MAX_KEY_CHARACTERS]:
        pools_to_try: list[list[dict[str, Any]]] = []
        if candidate.profile_pool:
            pools_to_try.append(candidate.profile_pool)
        if boss_pool and boss_pool not in pools_to_try:
            pools_to_try.append(boss_pool)
        if not pools_to_try:
            continue

        card: dict[str, Any] | None = None
        card_pointers: list[dict[str, str]] = []
        for pool in pools_to_try:
            summary, used = synthesize_key_character_summary(
                pool,
                boss_name=candidate.name,
                instance_name=instance_name,
            )
            if lint_key_character_summary(
                summary, boss_name=candidate.name, instance_name=instance_name
            ) or lint_passthrough_fragment(summary):
                summary, used = fallback_key_character_summary(
                    pool,
                    boss_name=candidate.name,
                    instance_name=instance_name,
                )
            if lint_key_character_summary(
                summary, boss_name=candidate.name, instance_name=instance_name
            ) or lint_passthrough_fragment(summary):
                continue
            pointers = _cap_card_pointers(
                _pointers_for_source_ids(pool, used, revision_map),
                max_count=3,
            )
            if not pointers and boss_pool is not pool:
                pointers = _cap_card_pointers(
                    _pointers_for_source_ids(boss_pool, used, revision_map),
                    max_count=3,
                )
            if not pointers:
                best_pool = pool if pool else boss_pool
                pointers = _cap_card_pointers(
                    _ensure_pointer_count(
                        [],
                        pool=best_pool,
                        revision_map=revision_map,
                        min_count=1,
                    ),
                    max_count=3,
                )
            if not pointers:
                continue
            role = candidate.role or "uncertain"
            role_reason = candidate.role_reason or "no_signal"
            # Hybrid: only spend an LLM call when deterministic signals were inconclusive.
            if role == "uncertain":
                role = classify_key_character_role_llm(
                    pool,
                    character_name=candidate.name,
                    instance_name=instance_name,
                    fallback_role="uncertain",
                )
                if role != "uncertain":
                    role_reason = "llm_tiebreaker"
            reason_codes: list[str] = []
            selection_reason = (selection_reasons or {}).get(candidate.name)
            if selection_reason:
                reason_codes.append(selection_reason)
            if candidate.source_section_role:
                reason_codes.append(candidate.source_section_role)
            if role_reason:
                reason_codes.append(f"role:{role}:{role_reason}")
            card = {
                "id": candidate.boss_id,
                "name": candidate.name,
                "summary": summary,
                "role": role,
                "wiki_ref": candidate.wiki_url or None,
                "decision_reason_codes": reason_codes,
                "thumbnail_asset_id": None,
            }
            card_pointers = pointers
            break
        if card is None:
            continue
        cards.append(card)
        provenance_map[str(card["id"])] = card_pointers
        used_source_ids.update(str(pointer["source_id"]) for pointer in card_pointers)
        if len(cards) >= INSTANCE_MAX_KEY_CHARACTERS:
            break
    return cards, provenance_map, used_source_ids


def build_instance_major_factions(
    *,
    instance_id: str,
    instance_name: str,
    parent_zone_id: str,
    parent_zone_name: str,
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    revision_map: dict[str, str],
    faction_profile_targets: list[dict[str, Any]] | None = None,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    scoped_targets = [
        row
        for row in (faction_profile_targets or [])
        if str(row.get("zone_id", "")).strip() == parent_zone_id
    ]
    merged_evidence = list(evidence_rows)
    if parent_zone_evidence_rows:
        merged_evidence.extend(
            row
            for row in parent_zone_evidence_rows
            if str(row.get("field_name", "")).strip() == "faction_pool"
        )
    zone_name = parent_zone_name.strip() or instance_name
    return build_major_factions(
        zone_id=parent_zone_id or instance_id,
        zone_name=zone_name,
        evidence_rows=merged_evidence,
        pools={
            **pools,
            "questline_pool": [],
            "quest_cluster_lore_pool": [],
            "quest_lore_pool": [],
            "currently_pool": pools.get("faction_role_pool", []),
            "history_pool": pools.get("faction_role_pool", []),
        },
        questline_rows=[],
        revision_map=revision_map,
        faction_profile_targets=scoped_targets,
        instance_name=instance_name,
    )


def _best_snippet_for_term(items: list[dict[str, Any]], term: str, min_words: int = 8) -> str:
    term_lower = term.lower()
    best = ""
    for item in items:
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        if term_lower in snippet.lower() and _word_count(snippet) >= min_words:
            return snippet
        if _word_count(snippet) > _word_count(best):
            best = snippet
    return best


def _history_sections_from_pool(
    history_pool: list[dict[str, Any]],
    *,
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    pool = history_pool or select_history_pool(_iter_evidence_items(evidence_rows, {"history_digest"}))
    cap = history_section_cap(pool) or MIN_HISTORY_SECTIONS
    draft_pool = cap_history_pool(pool, cap)
    sections, used = fallback_history_sections(draft_pool, max_sections=cap)
    if sections:
        return sections, used
    return [], []


def _draft_history_pool(history_pool: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    max_history = history_section_cap(history_pool)
    if max_history <= 0:
        return [], 0
    return cap_history_pool(history_pool, max_history), max_history


def _finalize_at_a_glance(
    *,
    zone_name: str,
    at_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    text, used = synthesize_at_a_glance(at_pool, max_words=MAX_AT_A_GLANCE_WORDS)
    if lint_at_a_glance(text, zone_name=zone_name):
        text, used = fallback_at_a_glance(at_pool)
        if lint_at_a_glance(text, zone_name=zone_name):
            text, used = "", []
    if not text:
        rescue_pool = at_pool or select_at_a_glance_pool(
            _iter_evidence_items(evidence_rows, {"at_a_glance_input", "history_digest"})
        )
        text, used = fallback_at_a_glance(rescue_pool)
        if lint_at_a_glance(text, zone_name=zone_name):
            text, used = "", []
    if not text:
        text = f"{zone_name} was a contested region shaped by war and later recovery efforts."
        used = []
    return text, used


def _finalize_currently(
    *,
    zone_name: str,
    at_a_glance: str,
    currently_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
) -> tuple[str, list[str]]:
    text, used = synthesize_currently(currently_pool, max_words=120)
    if lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance):
        text, used = fallback_currently(currently_pool)
        if lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance):
            text, used = "", []
    if not text:
        rescue_pool = currently_pool or select_currently_pool(pools, zone_name=zone_name)
        text, used = fallback_currently(rescue_pool)
        if lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance):
            text, used = "", []
    if not text:
        text = (
            f"{zone_name} remains a contested frontier where crusaders and rival factions "
            "continue to clash over ruined strongholds."
        )
        used = []
    return text, used


def _finalize_history_sections(
    *,
    history_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    max_history: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    section_cap = max_history or MIN_HISTORY_SECTIONS
    lint_cap = max_history or MAX_HISTORY_SECTIONS
    sections, used = synthesize_history_sections(history_pool, max_sections=section_cap)
    if lint_history_sections(sections, max_sections=lint_cap):
        sections, used = fallback_history_sections(history_pool, max_sections=section_cap)
        if lint_history_sections(sections, max_sections=lint_cap):
            sections, used = [], []
    if not sections:
        pool_sections, pool_used = _history_sections_from_pool(history_pool, evidence_rows=evidence_rows)
        if pool_sections:
            kept_sections = [
                section
                for section in pool_sections
                if not lint_history_sections([section], max_sections=1)
            ]
            candidate_sections = kept_sections or pool_sections
            if not lint_history_sections(candidate_sections, max_sections=lint_cap):
                sections = candidate_sections[:section_cap]
                used = pool_used
    return sections, used


def _first_snippet(
    evidence_rows: list[dict[str, Any]],
    fields: set[str],
    min_words: int = 1,
) -> str:
    item = _first_item(evidence_rows, fields, min_words=min_words)
    if item is None:
        return ""
    return str(item["snippet"])


def _first_item(
    evidence_rows: list[dict[str, Any]],
    fields: set[str],
    min_words: int = 1,
) -> dict[str, Any] | None:
    items = _iter_evidence_items(evidence_rows, fields)
    if not items:
        return None
    for item in items:
        snippet = str(item["snippet"])
        lowered = snippet.lower()
        if "(lore)" in lowered and _word_count(snippet) < 10:
            continue
        if _word_count(snippet) >= min_words:
            return item
    return items[0]


def _finalize_faction_card(
    candidate: FactionCandidate,
    *,
    zone_name: str,
    subregion_tokens: list[str],
    instance_name: str | None = None,
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    pools_to_try = finalize_evidence_pools(candidate)
    if not pools_to_try:
        return None, [], []

    for pool in pools_to_try:
        summary, used = synthesize_faction_summary(
            pool,
            faction_name=candidate.name,
            zone_name=zone_name,
            max_words=40,
            subregion_tokens=subregion_tokens,
            instance_name=instance_name,
        )
        summary = ensure_sentence_terminator(summary)
        if not lint_faction_summary(summary, zone_name=zone_name, subregion_tokens=subregion_tokens):
            return (
                {
                    "id": candidate.faction_id,
                    "name": candidate.name,
                    "summary": summary,
                    "wiki_url": candidate.wiki_url,
                },
                used,
                pool,
            )
        summary, used = fallback_faction_summary(
            pool,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
        )
        summary = ensure_sentence_terminator(summary)
        if not lint_faction_summary(summary, zone_name=zone_name, subregion_tokens=subregion_tokens):
            return (
                {
                    "id": candidate.faction_id,
                    "name": candidate.name,
                    "summary": summary,
                    "wiki_url": candidate.wiki_url,
                },
                used,
                pool,
            )
    return None, [], []


def build_major_factions(
    *,
    zone_id: str,
    zone_name: str,
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    questline_rows: list[dict[str, Any]],
    revision_map: dict[str, str],
    faction_profile_targets: list[dict[str, Any]] | None = None,
    instance_name: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    subregion_tokens = extract_subregion_tokens(pools.get("location_seed_pool", []), zone_name=zone_name)
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=evidence_rows,
        pools=pools,
        faction_profile_targets=faction_profile_targets,
        v3_rows=questline_rows,
    )
    target_count, queue = candidates_for_finalize(
        candidates,
        zone_name=zone_name,
        subregion_tokens=subregion_tokens,
    )
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    for candidate in queue:
        if len(cards) >= MAX_FACTION_CARDS:
            break
        card, used, pool = _finalize_faction_card(
            candidate,
            zone_name=zone_name,
            subregion_tokens=subregion_tokens,
            instance_name=instance_name,
        )
        if card is None:
            continue
        cards.append(card)
        pointers = _cap_card_pointers(_pointers_for_source_ids(pool, used, revision_map))
        if pointers:
            provenance_map[str(card["id"])] = pointers
        if target_count and len(cards) >= target_count:
            break
    return cards, provenance_map


def _finalize_location_card(
    candidate: LocationCandidate,
    *,
    zone_name: str,
    location_decision_map: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    pools_to_try = finalize_location_evidence_pools(candidate)
    if not pools_to_try:
        return None, [], []
    reason_codes = _decision_reason_codes(candidate.location_id, location_decision_map)

    for pool in pools_to_try:
        summary, used = synthesize_location_summary(
            pool,
            location_name=candidate.name,
            zone_name=zone_name,
            max_words=50,
        )
        summary = ensure_location_sentence_terminator(summary)
        if not lint_location_summary(summary, zone_name=zone_name, location_name=candidate.name):
            return (
                {
                    "id": candidate.location_id,
                    "name": candidate.name,
                    "summary": summary,
                    "wiki_url": candidate.wiki_url,
                    "location_type": (
                        "major_location"
                        if candidate.classification == "major_location_candidate"
                        else candidate.classification or "major_location"
                    ),
                    "significance": candidate.classification or "major_location_candidate",
                    "decision_reason_codes": reason_codes,
                },
                used,
                pool,
            )
        summary, used = fallback_location_summary(
            pool,
            zone_name=zone_name,
            location_name=candidate.name,
        )
        summary = ensure_location_sentence_terminator(summary)
        if summary and not lint_location_summary(summary, zone_name=zone_name, location_name=candidate.name):
            return (
                {
                    "id": candidate.location_id,
                    "name": candidate.name,
                    "summary": summary,
                    "wiki_url": candidate.wiki_url,
                    "location_type": (
                        "major_location"
                        if candidate.classification == "major_location_candidate"
                        else candidate.classification or "major_location"
                    ),
                    "significance": candidate.classification or "major_location_candidate",
                    "decision_reason_codes": reason_codes,
                },
                used,
                pool,
            )
    return None, [], []


def build_location_cards(
    *,
    zone_id: str,
    zone_name: str,
    location_rows: list[dict[str, Any]],
    location_candidate_map: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
    revision_map: dict[str, str],
    location_profile_targets: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    candidates = collect_location_candidates(
        zone_id=zone_id,
        zone_name=zone_name,
        location_rows=location_rows,
        location_candidate_map=location_candidate_map,
        location_decision_map=location_decision_map,
        pools=pools,
        location_profile_targets=location_profile_targets,
    )
    target_count, queue = location_candidates_for_finalize(candidates)
    cards: list[dict[str, Any]] = []
    provenance_map: dict[str, list[dict[str, str]]] = {}
    for candidate in queue:
        if len(cards) >= MAX_LOCATION_CARDS:
            break
        card_body, used_ids, source_pool = _finalize_location_card(
            candidate,
            zone_name=zone_name,
            location_decision_map=location_decision_map,
        )
        if card_body is None:
            continue
        card = {
            **card_body,
            "zone_id": zone_id,
            "ui_hints": {"render_as": card_body.get("location_type", "major_location")},
            "provenance": [],
        }
        cards.append(card)
        pointers = _cap_card_pointers(_pointers_for_source_ids(source_pool, used_ids, revision_map))
        if pointers:
            provenance_map[candidate.location_id] = pointers
        if len(cards) >= target_count and target_count > 0:
            break
    return cards, provenance_map


def _instance_link_candidates(
    zone_id: str,
    instance_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in instance_rows:
        if str(row.get("source_zone_id", "")) != zone_id:
            continue
        name = str(row.get("name", "")).strip()
        instance_id = str(row.get("instance_id", "")).strip()
        if not name or not instance_id:
            continue
        candidates.append(
            {
                "id": instance_id,
                "name": name,
                "thumbnail_asset_id": None,
            }
        )
    return candidates[:8]


_MAX_CLUSTER_CARDS = ZONE_MAX_TOTAL_QUESTLINE_CARDS
_MAX_CHAIN_REFS = 12


def _faction_scoped_lore_pool(
    pool: list[dict[str, Any]],
    quests: list[dict[str, Any]],
    faction: str,
) -> list[dict[str, Any]]:
    if faction not in {"alliance", "horde"}:
        return pool
    quest_node_ids = {
        str(row.get("node_id", "")).strip()
        for row in quests
        if isinstance(row, dict)
        and str(row.get("faction_binding", "shared")).strip().lower() == faction
    }
    if not quest_node_ids:
        return pool
    scoped = [
        item
        for item in pool
        if str(item.get("quest_node_id", "")).strip() in quest_node_ids
        or str(item.get("quest_node_id", "")).strip() == ""
    ]
    return scoped or pool


def _split_chain_refs(chain_refs: list[str]) -> tuple[list[str], list[str]]:
    if len(chain_refs) <= _MAX_CHAIN_REFS:
        return chain_refs, []
    return chain_refs[:_MAX_CHAIN_REFS], chain_refs[_MAX_CHAIN_REFS:]


def _append_questline_card(
    *,
    major_questlines: list[dict[str, Any]],
    questline_provenance_by_bucket: dict[str, dict[str, list[dict[str, str]]]],
    cluster_id: str,
    cluster_title: str,
    faction: str,
    start_anchor: str,
    chain_refs: list[str],
    wiki_refs: list[str],
    cta: str,
    scoped_pool: list[dict[str, Any]],
    cta_used: list[str],
    revision_map: dict[str, str],
    questline_decision: dict[str, Any] | None,
    used_source_ids: set[str],
    card_suffix: str = "",
    zone_name: str = "",
    cluster_decision: dict[str, Any] | None = None,
    card_id: str = "",
) -> None:
    resolved_card_id = card_id.strip() or f"cluster-{cluster_id}{card_suffix}"
    if zone_name.strip():
        cta = strip_zone_name_from_cta(cta, zone_name=zone_name)
    cta = finalize_cta_hook(cta)
    include_decision = str(
        (cluster_decision or {}).get("final_decision")
        or (questline_decision or {}).get("final_decision")
        or "include"
    )
    reason_codes = list((cluster_decision or {}).get("reason_codes") or [])
    if not reason_codes:
        reason_codes = list((questline_decision or {}).get("reason_codes") or ["graph_depth"])
    major_questlines.append(
        {
            "id": resolved_card_id,
            "title": cluster_title,
            "faction": faction,
            "cta_hook": cta,
            "start_anchor": start_anchor,
            "chain_refs": chain_refs,
            "include_decision": include_decision,
            "reason_codes": reason_codes,
            "wiki_refs": wiki_refs,
        }
    )
    pointers = _cap_card_pointers(_pointers_for_source_ids(scoped_pool, cta_used, revision_map))
    if not pointers:
        pointers = _cap_card_pointers(
            _ensure_pointer_count(
                [],
                pool=scoped_pool,
                revision_map=revision_map,
                min_count=1,
            )
        )
    if pointers:
        bucket = _provenance_bucket_for_faction(faction)
        questline_provenance_by_bucket[bucket][resolved_card_id] = pointers
        for pointer in pointers:
            used_source_ids.add(pointer["source_id"])


def _group_v3_clusters(questline_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: dict[str, dict[str, Any]] = {}
    for row in questline_rows:
        if str(row.get("node_type", "quest")) != "quest":
            continue
        cluster_id = str(row.get("cluster_id", "")).strip() or "cluster-main"
        bucket = clusters.get(cluster_id)
        if bucket is None:
            bucket = {
                "cluster_id": cluster_id,
                "cluster_title": str(row.get("cluster_title", "Main storylines")),
                "cluster_order": int(row.get("cluster_order", 0) or 0),
                "quests": [],
            }
            clusters[cluster_id] = bucket
        bucket["quests"].append(row)
    grouped = list(clusters.values())
    grouped.sort(key=lambda item: (int(item.get("cluster_order", 0)), str(item.get("cluster_id", ""))))
    for bucket in grouped:
        bucket["quests"].sort(key=lambda row: int(row.get("order_in_cluster", 0) or 0))
    return grouped


def _majority_faction(bindings: list[str]) -> str:
    counts: dict[str, int] = {}
    for binding in bindings:
        key = binding.strip().lower() or "shared"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "shared"
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "shared"
    winner = ranked[0][0]
    if winner == "neutral":
        return "shared"
    if winner in {"alliance", "horde", "shared"}:
        return winner
    return "shared"


def _cluster_lore_pool(
    pools: dict[str, list[dict[str, Any]]],
    cluster_id: str,
) -> list[dict[str, Any]]:
    cluster_items = [
        item for item in pools.get("quest_cluster_lore_pool", []) if str(item.get("cluster_id", "")) == cluster_id
    ]
    if cluster_items:
        return cluster_items
    return [
        item
        for item in pools.get("quest_lore_pool", [])
        if str(item.get("cluster_id", "")) == cluster_id
    ]


def _provenance_bucket_for_faction(faction: str) -> str:
    if faction == "alliance":
        return "major_questlines_alliance"
    if faction == "horde":
        return "major_questlines_horde"
    return "major_questlines_shared"


def build_zone_page(
    fact_pack: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    questline_rows: list[dict[str, Any]],
    location_rows: list[dict[str, Any]],
    instance_rows: list[dict[str, Any]],
    location_candidate_map: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    questline_decision: dict[str, Any] | None,
    *,
    questline_cluster_decision_map: dict[str, dict[str, Any]] | None = None,
    questline_card_metadata: dict[str, dict[str, Any]] | None = None,
    included_cluster_ids: list[str] | None = None,
    faction_profile_targets: list[dict[str, Any]] | None = None,
    location_profile_targets: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    zone_id = str(fact_pack.get("entity_id", "zone-unknown"))
    name = str(fact_pack.get("name", zone_id))
    revision_map, source_urls = build_revision_index(fact_pack, snapshots)
    source_url = ""
    for source_id, url in source_urls.items():
        if source_id and url:
            source_url = str(url)
            break
    pools = _build_evidence_pools(evidence_rows)
    used_source_ids: set[str] = set()

    at_pool = select_at_a_glance_pool(pools["at_a_glance_pool"])
    currently_pool = select_currently_pool(pools, zone_name=name)
    history_pool = select_history_pool(pools["history_pool"])
    draft_history_pool, max_history = _draft_history_pool(history_pool)

    at_a_glance, at_glance_used = _finalize_at_a_glance(
        zone_name=name,
        at_pool=at_pool,
        evidence_rows=evidence_rows,
    )

    currently, currently_used = _finalize_currently(
        zone_name=name,
        at_a_glance=at_a_glance,
        currently_pool=currently_pool,
        evidence_rows=evidence_rows,
        pools=pools,
    )

    at_glance_pool = at_pool or pools["at_a_glance_pool"]
    at_a_glance_pointers = _pointers_for_source_ids(at_glance_pool, at_glance_used, revision_map)
    at_a_glance_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            at_a_glance_pointers,
            pool=at_glance_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(at_a_glance)),
        ),
        max_count=3,
    )
    currently_pointer_pool = currently_pool or pools["currently_pool"]
    currently_pointers = _pointers_for_source_ids(currently_pointer_pool, currently_used, revision_map)
    currently_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            currently_pointers,
            pool=currently_pointer_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(currently)),
        ),
        max_count=3,
    )
    for pointer in at_a_glance_pointers + currently_pointers:
        used_source_ids.add(pointer["source_id"])

    history_sections, history_used = _finalize_history_sections(
        history_pool=draft_history_pool,
        evidence_rows=evidence_rows,
        max_history=max_history,
    )
    history_sections = _attach_history_source_refs(
        history_sections,
        draft_history_pool or history_pool or pools["history_pool"],
        revision_map,
    )
    history_pointer_pool = draft_history_pool or history_pool or pools["history_pool"]
    history_pointers = _pointers_for_source_ids(history_pointer_pool, history_used, revision_map)
    if not history_pointers:
        history_pointers = _history_pointers_from_sections(history_sections)
    history_text = " ".join(
        str(section.get("body", "")).strip()
        for section in history_sections
        if isinstance(section, dict)
    )
    history_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            history_pointers,
            pool=history_pointer_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(history_text)),
        ),
        max_count=3,
    )
    for pointer in history_pointers:
        used_source_ids.add(pointer["source_id"])

    major_questlines: list[dict[str, Any]] = []
    questline_overflow_decisions: list[dict[str, Any]] = []
    questline_provenance_by_bucket: dict[str, dict[str, list[dict[str, str]]]] = {
        "major_questlines_alliance": {},
        "major_questlines_horde": {},
        "major_questlines_shared": {},
    }
    questline_decision_value = str((questline_decision or {}).get("final_decision", "")).strip()
    active_questline_rows = questline_rows
    if questline_decision_value not in {"", "include", "defer"}:
        active_questline_rows = []
    cluster_groups = _group_v3_clusters(active_questline_rows)
    rank_order = {cluster_id: index for index, cluster_id in enumerate(included_cluster_ids or [])}
    if rank_order:
        cluster_groups = [
            cluster
            for cluster in cluster_groups
            if str(cluster.get("cluster_id", "")) in rank_order
        ]
        cluster_groups.sort(
            key=lambda cluster: rank_order.get(str(cluster.get("cluster_id", "")), 999)
        )
    elif questline_cluster_decision_map:
        cluster_groups = [
            cluster
            for cluster in cluster_groups
            if str(
                (questline_cluster_decision_map or {})
                .get(str(cluster.get("cluster_id", "")), {})
                .get("final_decision", "include")
            )
            in {"include", "defer", ""}
        ]
    emitted_cards = 0
    for cluster in cluster_groups:
        if emitted_cards >= _MAX_CLUSTER_CARDS:
            questline_overflow_decisions.append(
                {
                    "entity_id": zone_id,
                    "entity_type": "questline_cluster",
                    "cluster_id": str(cluster.get("cluster_id", "")),
                    "reason": "questline_cluster_cap",
                }
            )
            continue
        cluster_id = str(cluster.get("cluster_id", "cluster-main"))
        cluster_decision = (questline_cluster_decision_map or {}).get(cluster_id)
        if cluster_decision and str(cluster_decision.get("final_decision", "")) not in {
            "include",
            "defer",
            "",
        }:
            questline_overflow_decisions.append(
                {
                    "entity_id": zone_id,
                    "entity_type": "questline_cluster",
                    "cluster_id": cluster_id,
                    "reason": "significance_excluded",
                    "decision": cluster_decision.get("final_decision"),
                }
            )
            continue
        quests = cluster.get("quests", [])
        if not isinstance(quests, list) or not quests:
            continue
        cluster_title = _sanitize_cluster_title(
            str(cluster.get("cluster_title", "Main storylines")),
            zone_name=name,
        )
        card_meta = (questline_card_metadata or {}).get(cluster_id, {})
        if str(card_meta.get("display_title", "")).strip():
            cluster_title = str(card_meta.get("display_title", "")).strip()
        faction = _majority_faction([str(row.get("faction_binding", "shared")) for row in quests if isinstance(row, dict)])
        first_quest = quests[0] if isinstance(quests[0], dict) else {}
        start_anchor = str(card_meta.get("start_anchor", "")).strip() or str(
            first_quest.get("title", cluster_title)
        )
        card_id_override = str(card_meta.get("card_id", "")).strip()
        suppress_continued_card = bool(card_meta.get("suppress_continued_card"))
        chain_refs = [str(row.get("node_id", "")) for row in quests if isinstance(row, dict) and row.get("node_id")]
        wiki_refs = [
            str(row.get("source_link", ""))
            for row in quests
            if isinstance(row, dict) and str(row.get("source_link", "")).strip()
        ]
        scoped_pool = _cluster_lore_pool(pools, cluster_id)
        scoped_pool = _faction_scoped_lore_pool(scoped_pool, quests, faction)
        if not scoped_pool:
            continue
        cta, cta_used = synthesize_questline_cta_hook(
            scoped_pool,
            arc_title=cluster_title,
            start_anchor=start_anchor,
            faction=faction,
            chain_refs=chain_refs,
            max_words=35,
        )
        if not cta:
            cta = _best_snippet_for_term(scoped_pool, cluster_title, min_words=8) or (
                f"Follow the {cluster_title} arc through its linked quests."
            )
        primary_refs, overflow_refs = _split_chain_refs(chain_refs)
        primary_wiki_refs = wiki_refs[: len(primary_refs)] if wiki_refs else []
        _append_questline_card(
            major_questlines=major_questlines,
            questline_provenance_by_bucket=questline_provenance_by_bucket,
            cluster_id=cluster_id,
            cluster_title=cluster_title,
            faction=faction,
            start_anchor=start_anchor,
            chain_refs=primary_refs,
            wiki_refs=primary_wiki_refs or wiki_refs[:1],
            cta=cta,
            scoped_pool=scoped_pool,
            cta_used=cta_used,
            revision_map=revision_map,
            questline_decision=questline_decision,
            used_source_ids=used_source_ids,
            zone_name=name,
            cluster_decision=cluster_decision,
            card_id=card_id_override,
        )
        emitted_cards += 1
        if overflow_refs:
            if suppress_continued_card:
                questline_overflow_decisions.append(
                    {
                        "entity_id": zone_id,
                        "entity_type": "questline_cluster",
                        "cluster_id": cluster_id,
                        "card_id": card_id_override or f"cluster-{cluster_id}",
                        "reason": "questline_chain_refs_cap",
                        "overflow_chain_refs": overflow_refs,
                    }
                )
                continue
            overflow_pool = _cluster_lore_pool(pools, cluster_id)
            overflow_pool = _faction_scoped_lore_pool(overflow_pool, quests, faction)
            overflow_cta, overflow_used = synthesize_card_summary(
                overflow_pool,
                subject=f"{cluster_title} (continued)",
                max_words=35,
                faction=faction,
            )
            if not overflow_cta:
                overflow_cta = f"Continue the {cluster_title} arc through its remaining linked quests."
            if emitted_cards < _MAX_CLUSTER_CARDS and overflow_pool:
                overflow_wiki = wiki_refs[len(primary_refs) :] if wiki_refs else []
                _append_questline_card(
                    major_questlines=major_questlines,
                    questline_provenance_by_bucket=questline_provenance_by_bucket,
                    cluster_id=cluster_id,
                    cluster_title=f"{cluster_title} (continued)",
                    faction=faction,
                    start_anchor=str(
                        next(
                            (
                                row.get("title", start_anchor)
                                for row in quests[len(primary_refs) :]
                                if isinstance(row, dict)
                            ),
                            start_anchor,
                        )
                    ),
                    chain_refs=overflow_refs[:_MAX_CHAIN_REFS],
                    wiki_refs=overflow_wiki or wiki_refs[-1:],
                    cta=overflow_cta,
                    scoped_pool=overflow_pool,
                    cta_used=overflow_used,
                    revision_map=revision_map,
                    questline_decision=questline_decision,
                    used_source_ids=used_source_ids,
                    card_suffix="-continued",
                    zone_name=name,
                    cluster_decision=cluster_decision,
                )
                emitted_cards += 1
            else:
                questline_overflow_decisions.append(
                    {
                        "entity_id": zone_id,
                        "entity_type": "questline_cluster",
                        "cluster_id": cluster_id,
                        "reason": "questline_chain_refs_cap",
                        "overflow_chain_refs": overflow_refs,
                    }
                )

    location_cards, landmark_provenance_map = build_location_cards(
        zone_id=zone_id,
        zone_name=name,
        location_rows=location_rows,
        location_candidate_map=location_candidate_map,
        location_decision_map=location_decision_map,
        pools=pools,
        revision_map=revision_map,
        location_profile_targets=location_profile_targets,
    )
    for pointers in landmark_provenance_map.values():
        for pointer in pointers:
            used_source_ids.add(pointer["source_id"])

    instance_links: list[dict[str, Any]] = []
    instance_provenance_map: dict[str, list[dict[str, str]]] = {}
    for candidate in _instance_link_candidates(zone_id, instance_rows):
        instance_name = str(candidate.get("name", "")).strip()
        scoped = [
            item
            for item in pools["instance_pool"]
            if instance_name.lower() in str(item.get("snippet", "")).lower()
        ] or pools["instance_pool"]
        summary, used_ids = synthesize_card_summary(scoped, subject=instance_name, max_words=35)
        if not summary:
            summary = _best_snippet_for_term(scoped, instance_name, min_words=10)
            if summary:
                used_ids = [
                    str(item.get("source_id", "")).strip()
                    for item in scoped
                    if instance_name.lower() in str(item.get("snippet", "")).lower()
                    and str(item.get("source_id", "")).strip()
                ]
        if not summary:
            continue
        summary = trim_instance_link_summary(summary)
        card = {**candidate, "summary": summary}
        instance_links.append(card)
        pointers = _cap_card_pointers(_pointers_for_source_ids(scoped, used_ids, revision_map))
        if pointers:
            instance_provenance_map[str(card["id"])] = pointers
            for pointer in pointers:
                used_source_ids.add(pointer["source_id"])

    faction_cards, faction_provenance_map = build_major_factions(
        zone_id=zone_id,
        zone_name=name,
        evidence_rows=evidence_rows,
        pools=pools,
        questline_rows=active_questline_rows,
        revision_map=revision_map,
        faction_profile_targets=faction_profile_targets,
    )
    for pointers in faction_provenance_map.values():
        for pointer in pointers:
            used_source_ids.add(pointer["source_id"])
    parent_continent = resolve_parent_continent(evidence_rows) or "unknown"
    page_entity = {
        "zone_id": zone_id,
        "name": name,
        "wiki_url": source_url or "https://warcraft.wiki.gg/",
        "parent_continent": parent_continent,
        "expansion_context": "retail",
        "at_a_glance": at_a_glance,
        "currently": currently,
        "history_sections": history_sections,
        "major_factions": faction_cards,
        "major_questlines": major_questlines,
        "location_cards": location_cards,
        "instance_links": instance_links,
        "glossary_refs": [],
        "provenance": {
            "at_a_glance": at_a_glance_pointers,
            "currently": currently_pointers,
            "history": history_pointers,
            "major_questlines_alliance": questline_provenance_by_bucket["major_questlines_alliance"],
            "major_questlines_horde": questline_provenance_by_bucket["major_questlines_horde"],
            "major_questlines_shared": questline_provenance_by_bucket["major_questlines_shared"],
            "major_characters": {},
            "major_factions": faction_provenance_map,
            "instances": instance_provenance_map,
            "major_landmarks": landmark_provenance_map,
            "glossary": {},
        },
    }
    sources = collect_sources_manifest(page_entity, revision_map, source_urls)
    page_entity["sources"] = sources or _source_entries(fact_pack)
    if questline_overflow_decisions:
        page_entity["draft_overflow_decisions"] = questline_overflow_decisions
    return page_entity


def build_instance_page(
    fact_pack: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    lore_source: dict[str, Any] | None,
    *,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
    faction_profile_targets: list[dict[str, Any]] | None = None,
    section_blocks: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    instance_id = str(fact_pack.get("entity_id", "instance-unknown"))
    name = str(fact_pack.get("name", instance_id))
    parent_zone_id = str(fact_pack.get("parent_zone_id", "zone-unknown"))
    revision_map, source_urls = build_revision_index(fact_pack, snapshots)
    source_url = ""
    for source_id, url in source_urls.items():
        if source_id and url:
            source_url = str(url)
            break
    inferred_type = "dungeon"
    lower_claims = " ".join(str(claim) for claim in fact_pack.get("claims", [])).lower()
    if "raid" in lower_claims:
        inferred_type = "raid"

    pools = _build_instance_evidence_pools(
        evidence_rows,
        instance_name=name,
        parent_zone_evidence_rows=parent_zone_evidence_rows,
    )
    used_source_ids: set[str] = set()

    at_a_glance, at_used, at_producing_pool = _finalize_instance_at_a_glance(
        instance_name=name,
        at_pool=select_at_a_glance_pool(pools["at_a_glance_pool"]),
        evidence_rows=evidence_rows,
    )
    at_pointers = _pointers_for_source_ids(at_producing_pool, at_used, revision_map)
    at_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            at_pointers,
            pool=at_producing_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(at_a_glance)),
        ),
        max_count=3,
    )
    used_source_ids.update(pointer["source_id"] for pointer in at_pointers)

    sparse_rescue_pool: list[dict[str, Any]] = []
    if pools.get("instance_lore_sparse"):
        sparse_rescue_pool = build_sparse_lore_rescue_pool(
            parent_lore_pool=pools["parent_lore_pool"],
            related_lore_pool=pools["related_lore_pool"],
            instance_name=name,
        )
    overview, overview_used, overview_pool = _finalize_instance_overview(
        instance_name=name,
        overview_pool=pools["overview_pool"],
        zone_mention_pool=pools["zone_mention_pool"],
        sparse_rescue_pool=sparse_rescue_pool,
    )
    overview_pointers = _pointers_for_source_ids(overview_pool, overview_used, revision_map)
    overview_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            overview_pointers,
            pool=overview_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(overview)),
        ),
        max_count=3,
    )
    used_source_ids.update(pointer["source_id"] for pointer in overview_pointers)
    # Cross-page lore counts as "used" only when a story-context provenance pointer
    # actually cites a parent/related source, so the lore_source flip stays accurate.
    cross_page_source_ids = {
        str(item.get("source_id", ""))
        for item in pools["parent_lore_pool"] + pools["related_lore_pool"]
    }
    cross_page_lore_used = any(
        pointer["source_id"] in cross_page_source_ids for pointer in overview_pointers
    )

    history_pool = select_history_pool(pools["history_pool"])
    draft_history_pool, instance_history_cap = _draft_history_pool(history_pool)
    if instance_history_cap <= 0:
        instance_history_cap = MAX_HISTORY_SECTIONS
    history_sections, history_used = _finalize_history_sections(
        history_pool=draft_history_pool or history_pool,
        evidence_rows=evidence_rows,
        max_history=instance_history_cap,
    )
    history_sections = _attach_history_source_refs(
        history_sections,
        draft_history_pool or history_pool or pools["history_pool"],
        revision_map,
    )
    history_pointer_pool = (
        draft_history_pool
        or history_pool
        or select_history_pool(_iter_evidence_items(evidence_rows, {"history_digest"}))
    )
    history_pointers = _pointers_for_source_ids(history_pointer_pool, history_used, revision_map)
    if not history_pointers:
        history_pointers = _history_pointers_from_sections(history_sections)
    history_text = " ".join(
        str(section.get("body", "")).strip()
        for section in history_sections
        if isinstance(section, dict)
    )
    history_pointers = _ensure_pointer_count(
        history_pointers,
        pool=history_pointer_pool,
        revision_map=revision_map,
        min_count=_pointer_count_for_words(_word_count(history_text)),
    )
    used_source_ids.update(pointer["source_id"] for pointer in history_pointers)

    blocks = section_blocks if section_blocks is not None else fact_pack.get("section_blocks", [])
    if not isinstance(blocks, list):
        blocks = []
    key_character_selection = build_instance_key_character_selection(
        instance_id=instance_id,
        instance_name=name,
        evidence_rows=evidence_rows,
        section_blocks=blocks,
        snapshots=snapshots,
        pools=pools,
    )
    key_characters, key_character_provenance, character_used = _finalize_key_characters(
        instance_name=name,
        boss_candidates=key_character_selection.cast,
        boss_pool=pools["boss_pool"],
        revision_map=revision_map,
        selection_reasons=key_character_selection.selection_reasons,
    )
    used_source_ids.update(character_used)

    major_factions, faction_provenance = build_instance_major_factions(
        instance_id=instance_id,
        instance_name=name,
        parent_zone_id=parent_zone_id,
        parent_zone_name=str(fact_pack.get("parent_zone_name", "")).strip(),
        evidence_rows=evidence_rows,
        pools=pools,
        revision_map=revision_map,
        faction_profile_targets=faction_profile_targets,
        parent_zone_evidence_rows=parent_zone_evidence_rows,
    )
    for pointers in faction_provenance.values():
        for pointer in pointers:
            used_source_ids.add(pointer["source_id"])

    page_entity = {
        "instance_id": instance_id,
        "name": name,
        "instance_type": inferred_type,
        "parent_zone_id": parent_zone_id,
        "expansion_context": "retail",
        "wiki_url": source_url or "https://warcraft.wiki.gg/",
        "at_a_glance": at_a_glance,
        "overview": overview,
        "history_sections": history_sections,
        "key_characters": key_characters,
        "major_factions": major_factions,
        "lore_source": (
            "linked_lore_page"
            if cross_page_lore_used
            else str((lore_source or {}).get("lore_source", "instance_page"))
        ),
        "lore_source_reason": (
            "cross_page_fusion"
            if cross_page_lore_used
            else (lore_source or {}).get("fallback_reason")
        ),
        "variant_policy": "standalone",
        "variant_reason_codes": [],
        "glossary_refs": [],
        "provenance": {
            "identity_header": at_pointers,
            "story_context": overview_pointers,
            "key_characters": key_character_provenance,
            "major_factions": faction_provenance,
            "glossary": {},
        },
    }
    sources = collect_sources_manifest(page_entity, revision_map, source_urls)
    page_entity["sources"] = sources or _source_entries(fact_pack)
    return page_entity
