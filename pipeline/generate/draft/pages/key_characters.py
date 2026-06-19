"""Instance key-character pool selection and card finalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import INSTANCE_MAX_KEY_CHARACTERS
from pipeline.discovery.entity_typing import normalize_title
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
from pipeline.generate.draft.instance_lint import (
    fallback_key_character_summary,
    lint_key_character_summary,
    lint_passthrough_fragment,
)
from pipeline.generate.draft.pages.assembly import (
    _build_instance_evidence_pools,
    _cap_card_pointers,
    _classic_excluded_names,
    _ensure_pointer_count,
    _extract_instance_structured_links,
    _pointers_for_source_ids,
)
from pipeline.generate.draft.prose_selection import (
    classify_key_character_role_llm,
    select_key_characters_from_pool,
)
from pipeline.generate.draft.prose_synthesis import (
    synthesize_key_character_summary,
)

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
    pool = prefilter_character_pool(
        raw_pool,
        instance_name=instance_name,
        excluded_normalized_names=_classic_excluded_names(snapshots, instance_id),
    )
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
