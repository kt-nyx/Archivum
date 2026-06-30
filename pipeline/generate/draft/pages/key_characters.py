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
    is_boss_section_role,
    merge_key_character_cast,
    merged_cast_candidates,
    must_include_key_character_names,
    prefilter_character_pool,
)
from pipeline.generate.draft.claim_routing import (
    KEY_CHARACTER_ROUTE,
    item_has_claim_views,
    key_character_unsafe_claim_views,
    route_claim_views_for_pool,
)
from pipeline.generate.draft.instance_lint import (
    MAX_KEY_CHARACTER_WORDS,
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
from pipeline.generate.draft.prose_gate import prose_gate_rejects
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
    remaining = [
        candidate for candidate in pool if normalize_title(candidate.name) not in cast_keys
    ]
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


def _merge_character_profile_evidence(
    cast: list[BossCandidate], character_pool: list[dict[str, Any]]
) -> None:
    """Slice D: attach crawled character-page biography to each cast member's profile_pool.

    The biography is prepended so identity ("who this figure is") leads the synthesis evidence ahead
    of the instance's structural-presence mentions. Spoiler bounding is unchanged — the finalizer
    still routes the merged pool through KEY_CHARACTER_ROUTE, dropping unsafe claim views.
    """
    if not cast or not character_pool:
        return
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in character_pool:
        name = str(item.get("character_name") or item.get("source_title") or "").strip()
        if not name:
            continue
        by_name.setdefault(normalize_title(name), []).append(item)
    if not by_name:
        return
    for candidate in cast:
        cand_key = normalize_title(candidate.name)
        matched = by_name.get(cand_key)
        if matched is None:
            # Tolerate page-title vs roster-name drift (page "Gandling" vs cast "Darkmaster
            # Gandling"): accept the first character whose name contains or is contained by the cast
            # name, so a one-word page still binds to a titled roster entry.
            for name_key, items in by_name.items():
                if name_key and (name_key in cand_key or cand_key in name_key):
                    matched = items
                    break
        if matched:
            candidate.profile_pool = list(matched) + list(candidate.profile_pool or [])


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

    # When the page yields a structural boss roster (adventure guide / dungeon journal / faculty /
    # boss table), that roster *is* the cast: don't pad it with the LLM, which otherwise pulls in
    # denizen trash (random skeletons) and narrative-only figures the gold cast excludes. The LLM
    # discovers the cast only for instances whose page exposes no structural roster.
    llm_names: list[str] = []
    remaining = INSTANCE_MAX_KEY_CHARACTERS - len(floor)
    if not floor and remaining > 0:
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
    _merge_character_profile_evidence(cast, pools.get("character_pool", []))
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


# Claim-type priority for surviving the key-character evidence cap. Presence-explaining claims —
# what the figure means to do (objective), the condition driving them (state), and who they are bound
# to (relationship) — must outrank generic identity facts and stray events, so a capped evidence
# window keeps the motivation that explains why they are here over a flavor quote or later-life
# trivia. Non-claim paragraph items (rollout fallback) carry no claim_type and keep original order.
_KEY_CHARACTER_CLAIM_TYPE_RANK: dict[str, int] = {
    "objective": 0,
    "state": 1,
    "relationship": 2,
    "identity": 3,
    "event": 4,
}
_KEY_CHARACTER_CLAIM_TYPE_DEFAULT_RANK = 5


def _view_mentions_instance(view: dict[str, Any], *, instance_key: str, instance_lower: str) -> bool:
    if not instance_key:
        return False
    text = f"{view.get('claim_text', '')} {view.get('snippet', '')}".lower()
    if instance_lower and instance_lower in text:
        return True
    entities = view.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if isinstance(entity, dict) and normalize_title(str(entity.get("name", ""))) == instance_key:
                return True
    return False


def _order_key_character_summary_views(
    views: list[dict[str, Any]], *, instance_name: str
) -> list[dict[str, Any]]:
    """Stable-rank routed claim views so presence-explaining claims survive the evidence cap.

    Claims naming this instance lead (they tie the figure directly to where the player meets them),
    then claims order by type so motivation and allegiance outrank identity facts and one-off events.
    The sort is stable, so within a tier the original block/extraction order is preserved.
    """
    instance_key = normalize_title(instance_name) if instance_name else ""
    instance_lower = instance_name.lower() if instance_name else ""

    def rank_key(indexed: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        index, view = indexed
        instance_tier = (
            0
            if _view_mentions_instance(view, instance_key=instance_key, instance_lower=instance_lower)
            else 1
        )
        claim_type = str(view.get("claim_type", "")).strip().lower()
        type_rank = _KEY_CHARACTER_CLAIM_TYPE_RANK.get(
            claim_type, _KEY_CHARACTER_CLAIM_TYPE_DEFAULT_RANK
        )
        return (instance_tier, type_rank, index)

    return [view for _, view in sorted(enumerate(views), key=rank_key)]


def _key_character_summary_pool(
    pool: list[dict[str, Any]], *, instance_name: str = ""
) -> list[dict[str, Any]]:
    routed = route_claim_views_for_pool(pool, KEY_CHARACTER_ROUTE)
    return _order_key_character_summary_views(routed, instance_name=instance_name)


def _structural_presence_summary_pool(
    *,
    candidate: BossCandidate,
    instance_name: str,
    source_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not source_pool or not is_boss_section_role(candidate.source_section_role):
        return []
    base = dict(source_pool[0])
    base["snippet"] = (
        f"{candidate.name} is present in {instance_name} as one of the setting's notable "
        f"figures, helping define the threats and power structure encountered there."
    )
    base["source_excerpt"] = str(source_pool[0].get("source_excerpt") or source_pool[0].get("snippet", ""))
    base["is_claim_view"] = True
    base["claim_id"] = ""
    base["spoiler_safety"] = "encounter_setup"
    return [base]


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
        structural_role = candidate.role or "uncertain"
        for pool in pools_to_try:
            source_pool = pool
            # Slice 9: encounter-mechanics / outcome claims (e.g. "Lilian Voss defeated",
            # "Course: Reeducation") are barred from character prose (clarification question 1).
            # The route already drops them from the safe summary pool; collect them here only to
            # tell the synthesizer what to avoid, and to record safe/unsafe counts in the sidecar.
            has_claim_views = any(item_has_claim_views(item) for item in source_pool)
            unsafe_views = key_character_unsafe_claim_views(source_pool)
            avoid_hints = [
                text
                for view in unsafe_views
                if (text := str(view.get("claim_text", "")).strip())
            ]
            summary_pool = _key_character_summary_pool(source_pool, instance_name=instance_name)
            safe_evidence_count = len(summary_pool)
            used_structural_fallback = False
            if not summary_pool:
                # Only unsafe / unlabeled encounter evidence remains: fall back to a restrained
                # structural-presence summary rather than letting spoiler text write the card.
                summary_pool = _structural_presence_summary_pool(
                    candidate=candidate,
                    instance_name=instance_name,
                    source_pool=source_pool,
                )
                used_structural_fallback = bool(summary_pool)
            if not summary_pool:
                continue
            summary_kwargs: dict[str, Any] = {}
            if avoid_hints:
                summary_kwargs["avoid_hints"] = avoid_hints
            summary, used = synthesize_key_character_summary(
                summary_pool,
                boss_name=candidate.name,
                instance_name=instance_name,
                structural_role=structural_role,
                max_words=MAX_KEY_CHARACTER_WORDS,
                **summary_kwargs,
            )
            if (
                lint_key_character_summary(
                    summary, boss_name=candidate.name, instance_name=instance_name
                )
                or lint_passthrough_fragment(summary)
                # Backstop a verbatim evidence echo from the synthesizer against the pool it drew
                # from (defect #4). The deterministic fallback below legitimately *borrows* a clean
                # sentence, so it is gated text-only (no source comparison).
                or prose_gate_rejects(
                    summary,
                    source_snippets=[str(row.get("snippet", "")) for row in summary_pool],
                )
            ):
                summary, used = fallback_key_character_summary(
                    summary_pool,
                    boss_name=candidate.name,
                    instance_name=instance_name,
                )
            if (
                lint_key_character_summary(
                    summary, boss_name=candidate.name, instance_name=instance_name
                )
                or lint_passthrough_fragment(summary)
                or prose_gate_rejects(summary)
            ):
                continue
            pointers = _cap_card_pointers(
                _pointers_for_source_ids(summary_pool, used, revision_map),
                max_count=3,
            )
            if not pointers and boss_pool is not summary_pool:
                pointers = _cap_card_pointers(
                    _pointers_for_source_ids(boss_pool, used, revision_map),
                    max_count=3,
                )
            if not pointers:
                best_pool = summary_pool if summary_pool else boss_pool
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
                    summary_pool,
                    character_name=candidate.name,
                    instance_name=instance_name,
                    fallback_role="uncertain",
                )
                if role != "uncertain":
                    role_reason = "llm_tiebreaker"
            # WS-4 confidence gate: stop padding the roster to the cap with narrative-only
            # mentions. A non-floor candidate must carry a real in-instance structural
            # signal; a pure narrative fallback (no boss/denizen section, no adventure-guide
            # signal) is dropped rather than emitted as a low-confidence "uncertain" card.
            # The boss floor (must_include) always passes, so confident bosses are never
            # dropped. card is still None here, so breaking the pool loop drops the
            # candidate via the `if card is None` guard below.
            is_floor = (selection_reasons or {}).get(candidate.name) == "must_include_floor"
            if not is_floor and candidate.source_section_role == "narrative_fallback":
                break
            reason_codes: list[str] = []
            selection_reason = (selection_reasons or {}).get(candidate.name)
            if selection_reason:
                reason_codes.append(selection_reason)
            if candidate.source_section_role:
                reason_codes.append(candidate.source_section_role)
            if role_reason:
                reason_codes.append(f"role:{role}:{role_reason}")
            # Slice 9 spoiler-safety audit. With claim views, record how much safe vs unsafe
            # evidence backed the summary and whether spoiler-unsafe evidence forced the restrained
            # structural fallback. Without claim views (paragraph fallback), no claim-level safety
            # was assessed, so say so honestly rather than reporting an unvetted "safe" count.
            if has_claim_views:
                reason_codes.append(
                    f"summary_evidence:safe={safe_evidence_count}:unsafe={len(unsafe_views)}"
                )
                if used_structural_fallback:
                    reason_codes.append("summary_source:structural_presence")
            else:
                reason_codes.append("summary_evidence:paragraph_fallback")
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
