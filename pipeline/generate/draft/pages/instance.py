"""Instance page builder (build_instance_page) and instance-only finalizers."""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.faction_scoring import (
    harvest_instance_anchor_tokens,
    harvest_instance_faction_targets,
)
from pipeline.generate.draft.instance_lint import (
    fallback_instance_overview,
    lint_overview,
    lint_passthrough_fragment,
)
from pipeline.generate.draft.instance_lint import (
    lint_at_a_glance as lint_instance_at_a_glance,
)
from pipeline.generate.draft.lore_selection import (
    build_sparse_lore_rescue_pool,
)
from pipeline.generate.draft.pages.assembly import (
    _attach_history_source_refs,
    _build_instance_evidence_pools,
    _cap_card_pointers,
    _ensure_pointer_count,
    _history_pointers_from_sections,
    _pointer_count_for_words,
    _pointer_for_item,
    _pointers_for_source_ids,
    _source_entries,
    _word_count,
)
from pipeline.generate.draft.pages.cards import (
    _finalize_history_sections,
    build_major_factions,
    prepare_history_synthesis_pool,
)
from pipeline.generate.draft.pages.key_characters import (
    InstanceKeyCharacterSelection,
    _finalize_key_characters,
    adventure_guide_overview_framing,
    build_instance_key_character_selection,
    resolve_adventure_guide_instance,
)
from pipeline.generate.draft.prose_election import (
    fallback_at_a_glance,
    select_at_a_glance_pool,
)
from pipeline.generate.draft.prose_gate import prose_gate_violations
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    MAX_HISTORY_SECTIONS,
)
from pipeline.generate.draft.prose_synthesis import (
    FIELD_STATUS_NO_EVIDENCE,
    FIELD_STATUS_OFFLINE_FALLBACK,
    FIELD_STATUS_OK,
    FIELD_STATUS_SYNTHESIS_FAILED,
    SYNTHESIS_MAX_ATTEMPTS,
    _evidence_snippets,
    llm_synthesis_active,
    passthrough_corpus,
    synthesize_at_a_glance,
    synthesize_instance_overview,
    synthesize_with_validation,
)
from pipeline.generate.draft.provenance import (
    build_revision_index,
    collect_sources_manifest,
    select_identity_url,
)


def _finalize_instance_at_a_glance(
    *,
    instance_name: str,
    at_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    reference_framing: str = "",
) -> tuple[str | None, list[str], list[dict[str, Any]], str]:
    """Instance at_a_glance: validation-driven retries, else explicit failure.

    Returns ``(text, used_source_ids, producing_pool, field_status)``. The live path never borrows
    a source snippet; the offline NO_LLM ladder keeps the sanctioned deterministic borrow.
    """
    if not at_pool:
        return None, [], [], FIELD_STATUS_NO_EVIDENCE

    def _reasons(candidate: str) -> list[str]:
        # Lint failures AND copied/truncated source fragments (mid-sentence start, missing
        # terminal punctuation). The Adventure Guide reference (when present) joins the copy
        # corpus via the driver so a caption lifted from it is rejected too.
        reasons = list(lint_instance_at_a_glance(candidate, instance_name=instance_name))
        reasons.extend(lint_passthrough_fragment(candidate))
        reasons.extend(prose_gate_violations(candidate))
        return reasons

    if not llm_synthesis_active():
        text, used = synthesize_at_a_glance(
            at_pool,
            max_words=MAX_AT_A_GLANCE_WORDS,
            subject=instance_name,
            reference_framing=reference_framing,
        )
        if _reasons(text):
            text, used = fallback_at_a_glance(at_pool)
            if _reasons(text):
                return None, [], [], FIELD_STATUS_SYNTHESIS_FAILED
        return text, used, at_pool, FIELD_STATUS_OFFLINE_FALLBACK

    def _call(reinforce: str) -> dict[str, Any]:
        text, used = synthesize_at_a_glance(
            at_pool,
            max_words=MAX_AT_A_GLANCE_WORDS,
            subject=instance_name,
            reference_framing=reference_framing,
            reinforce=reinforce,
        )
        return {"text": text, "used": used}

    corpus = _evidence_snippets(at_pool)
    if reference_framing:
        corpus = [*corpus, reference_framing]
    result = synthesize_with_validation(
        call=_call,
        extract_bodies=lambda payload: [str(payload.get("text", ""))],
        validate=lambda payload: _reasons(str(payload.get("text", ""))),
        source_snippets=corpus,
        label="instance_at_a_glance",
    )
    if not result.ok:
        return None, [], [], FIELD_STATUS_SYNTHESIS_FAILED
    return (
        str(result.payload.get("text", "")),
        list(result.payload.get("used", [])),
        at_pool,
        FIELD_STATUS_OK,
    )


def _finalize_instance_overview(
    *,
    instance_name: str,
    overview_pool: list[dict[str, Any]],
    zone_mention_pool: list[dict[str, Any]],
    sparse_rescue_pool: list[dict[str, Any]] | None = None,
    reference_framing: str = "",
) -> tuple[str | None, list[str], list[dict[str, Any]], str]:
    """Instance overview: validation-driven retries per pool, else explicit failure."""
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
    if not pools_to_try:
        return None, [], [], FIELD_STATUS_NO_EVIDENCE

    def _reject_reasons(candidate: str, snippets: list[str] | None) -> list[str]:
        reasons = list(lint_overview(candidate, instance_name=instance_name))
        if lint_passthrough_fragment(candidate):
            reasons.append("passthrough_fragment")
        reasons.extend(prose_gate_violations(candidate, source_snippets=snippets))
        return reasons

    live = llm_synthesis_active()
    for pool_index, pool in enumerate(pools_to_try):
        # Source-aware passthrough: reject a verbatim copy of the evidence (the licensing
        # exposure). Inactive offline (``passthrough_corpus`` returns None), where borrowing is the
        # sanctioned fallback. The Adventure Guide reference (when present, live only) joins the
        # copy corpus so an overview lifted from it is rejected too.
        pool_snippets = passthrough_corpus(pool)
        gate_snippets = pool_snippets
        if pool_snippets is not None and reference_framing:
            gate_snippets = [*pool_snippets, reference_framing]
        if not live:
            text, used = synthesize_instance_overview(
                pool, instance_name=instance_name, reference_framing=reference_framing
            )
            if not _reject_reasons(text, gate_snippets):
                finalize_trace.record("overview.finalize", outcome="no_llm", gate_active=False)
                return text, used, pool, FIELD_STATUS_OFFLINE_FALLBACK
            text, used = fallback_instance_overview(pool, instance_name=instance_name)
            if not _reject_reasons(text, gate_snippets):
                finalize_trace.record(
                    "overview.finalize", outcome="no_llm_fallback", gate_active=False
                )
                return text, used, pool, FIELD_STATUS_OFFLINE_FALLBACK
            continue

        def _call(reinforce: str, pool: list[dict[str, Any]] = pool) -> dict[str, Any]:
            text, used = synthesize_instance_overview(
                pool,
                instance_name=instance_name,
                reference_framing=reference_framing,
                reinforce=reinforce,
            )
            return {"text": text, "used": used}

        def _validate(
            payload: dict[str, Any], snippets: list[str] | None = gate_snippets
        ) -> list[str]:
            return _reject_reasons(str(payload.get("text", "")), snippets)

        result = synthesize_with_validation(
            call=_call,
            extract_bodies=lambda payload: [str(payload.get("text", ""))],
            validate=_validate,
            # Copy detection runs inside _reject_reasons via the source-aware gate corpus.
            source_snippets=None,
            label="overview",
            max_attempts=SYNTHESIS_MAX_ATTEMPTS if pool_index == 0 else 1,
        )
        if result.ok:
            finalize_trace.record("overview.finalize", outcome="llm", gate_active=True)
            return (
                str(result.payload.get("text", "")),
                list(result.payload.get("used", [])),
                pool,
                FIELD_STATUS_OK,
            )
    finalize_trace.record(
        "overview.finalize",
        outcome="failed" if live else "empty",
        gate_active=live,
    )
    return None, [], [], FIELD_STATUS_SYNTHESIS_FAILED


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
    snapshots: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    # WS-8: harvest faction candidates from the instance's *own* evidence first. Scholomance et al.
    # carry no faction_pool evidence, so the parent-zone-scoped path returns nothing despite the page
    # being saturated with Scourge / Cult of the Damned.
    native_targets, native_role_pool = harvest_instance_faction_targets(
        instance_id=instance_id,
        instance_name=instance_name,
        evidence_rows=evidence_rows,
        snapshots=snapshots or [],
    )
    if native_targets:
        role_pool = native_role_pool or pools.get("faction_role_pool", [])
        anchor_tokens = harvest_instance_anchor_tokens(
            evidence_rows, instance_name=instance_name
        )
        if parent_zone_name.strip():
            anchor_tokens.append(parent_zone_name.strip())
        cards, provenance = build_major_factions(
            zone_id=instance_id,
            zone_name=instance_name,
            evidence_rows=evidence_rows,
            pools={
                **pools,
                "questline_pool": [],
                "quest_cluster_lore_pool": [],
                "quest_lore_pool": [],
                "faction_role_pool": role_pool,
                "currently_pool": role_pool,
                "history_pool": role_pool,
            },
            questline_rows=[],
            revision_map=revision_map,
            faction_profile_targets=native_targets,
            instance_name=instance_name,
            extra_subregion_tokens=anchor_tokens,
        )
        if cards:
            return cards, provenance

    # Fallback: the parent zone's faction targets + faction_pool evidence.
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


def build_instance_page(
    fact_pack: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    lore_source: dict[str, Any] | None,
    *,
    parent_zone_evidence_rows: list[dict[str, Any]] | None = None,
    faction_profile_targets: list[dict[str, Any]] | None = None,
    section_blocks: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    selection_sink: list[InstanceKeyCharacterSelection] | None = None,
) -> dict[str, Any]:
    instance_id = str(fact_pack.get("entity_id", "instance-unknown"))
    name = str(fact_pack.get("name", instance_id))
    parent_zone_id = str(fact_pack.get("parent_zone_id", "zone-unknown"))
    revision_map, source_urls = build_revision_index(fact_pack, snapshots)
    source_url = select_identity_url(source_urls, name)
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

    # The game's dedicated Adventure Guide page for this instance (per-boss blurbs + an intro),
    # resolved once and reused as reference framing across overview, at_a_glance, and key characters.
    # Gated to live LLM runs inside the resolver; ``None`` (or partial content) degrades to no
    # framing at each use site, so instances with no / partial Adventure Guide coverage are unchanged.
    adventure_guide = resolve_adventure_guide_instance(name)
    ag_overview_framing = adventure_guide_overview_framing(adventure_guide)

    field_status: dict[str, str] = {}
    at_a_glance, at_used, at_producing_pool, field_status["at_a_glance"] = (
        _finalize_instance_at_a_glance(
            instance_name=name,
            at_pool=select_at_a_glance_pool(pools["at_a_glance_pool"]),
            evidence_rows=evidence_rows,
            reference_framing=ag_overview_framing,
        )
    )
    at_pointers = _pointers_for_source_ids(at_producing_pool, at_used, revision_map)
    at_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            at_pointers,
            pool=at_producing_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(at_a_glance or "")),
        ),
        max_count=3,
    )
    if at_a_glance is None:
        at_pointers = []
    used_source_ids.update(pointer["source_id"] for pointer in at_pointers)

    sparse_rescue_pool: list[dict[str, Any]] = []
    if pools.get("instance_lore_sparse"):
        sparse_rescue_pool = build_sparse_lore_rescue_pool(
            parent_lore_pool=pools["parent_lore_pool"],
            related_lore_pool=pools["related_lore_pool"],
            instance_name=name,
        )
    overview, overview_used, overview_pool, field_status["overview"] = (
        _finalize_instance_overview(
            instance_name=name,
            overview_pool=pools["overview_pool"],
            zone_mention_pool=pools["zone_mention_pool"],
            sparse_rescue_pool=sparse_rescue_pool,
            reference_framing=ag_overview_framing,
        )
    )
    overview_pointers = _pointers_for_source_ids(overview_pool, overview_used, revision_map)
    overview_pointers = _cap_card_pointers(
        _ensure_pointer_count(
            overview_pointers,
            pool=overview_pool,
            revision_map=revision_map,
            min_count=_pointer_count_for_words(_word_count(overview or "")),
        ),
        max_count=3,
    )
    if overview is None:
        overview_pointers = []
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

    # Raw routed history pool stays the coverage pool (claim-level setup-bridge planning); the
    # synthesis pool is consolidated to paragraphs before select_history_pool's word-count gate.
    history_pool = pools["history_pool"]
    draft_history_pool, instance_history_cap = prepare_history_synthesis_pool(history_pool)
    if instance_history_cap <= 0:
        instance_history_cap = MAX_HISTORY_SECTIONS
    section_coverage_decisions: list[dict[str, Any]] = []
    history_sections, history_used, field_status["history"] = _finalize_history_sections(
        history_pool=draft_history_pool or history_pool,
        evidence_rows=evidence_rows,
        max_history=instance_history_cap,
        coverage_pool=history_pool,
        subject_id=instance_id,
        coverage_sink=section_coverage_decisions,
        coverage_pointer_builder=lambda item, ordinal: _pointer_for_item(
            item, revision_map, ordinal
        ),
    )
    history_sections = _attach_history_source_refs(
        history_sections,
        draft_history_pool or history_pool or pools["history_pool"],
        revision_map,
    )
    history_pointer_pool = (
        draft_history_pool
        or history_pool
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
    # Single source of truth: the draft writer reuses this selection to build the decision
    # sidecar (popped before serialization), so the page-emitted cast and the sidecar merge
    # ranks can never diverge from two independent LLM passes.
    key_characters, key_character_provenance, character_used = _finalize_key_characters(
        instance_name=name,
        boss_candidates=key_character_selection.cast,
        boss_pool=pools["boss_pool"],
        revision_map=revision_map,
        selection_reasons=key_character_selection.selection_reasons,
        adventure_guide=adventure_guide,
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
        snapshots=snapshots,
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
        "field_status": field_status,
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
    # Hand the computed selection back to the caller (the draft writer) so the decision
    # sidecar reuses it instead of recomputing via a second, divergent LLM pass. Kept off
    # the returned dict so the page stays JSON-serializable for every other caller.
    if selection_sink is not None:
        selection_sink.append(key_character_selection)
    if section_coverage_decisions:
        page_entity["section_coverage_decisions"] = section_coverage_decisions
    return page_entity
