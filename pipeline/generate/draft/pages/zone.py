"""Zone page builder (build_zone_page) and zone-only prose finalizers."""

from __future__ import annotations

from typing import Any

from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import ZONE_PAGE_BUDGET_RULES
from pipeline.discovery.geography import resolve_parent_continent
from pipeline.discovery.questline_card_polish import render_questline_title
from pipeline.generate.draft.instance_link_lint import (
    MAX_INSTANCE_LINK_WORDS,
    trim_instance_link_summary,
)
from pipeline.generate.draft.instance_lint import (
    lint_passthrough_fragment,
)
from pipeline.generate.draft.pages.assembly import (
    _attach_history_source_refs,
    _build_evidence_pools,
    _cap_card_pointers,
    _history_pointers_from_sections,
    _pointer_for_item,
    _pointers_for_evidence_ids,
    _sanitize_cluster_title,
    _source_entries,
    _word_count,
    citation_shortfall_reasons,
)
from pipeline.generate.draft.pages.cards import (
    _finalize_history_sections,
    build_location_cards,
    build_major_factions,
    prepare_history_synthesis_pool,
)
from pipeline.generate.draft.pages.questlines import (
    _MAX_CHAIN_REFS,
    _MAX_CLUSTER_CARDS,
    _append_questline_card,
    _cluster_lore_pool,
    _faction_scoped_lore_pool,
    _group_v3_clusters,
    _majority_faction,
    _split_chain_refs,
)
from pipeline.generate.draft.prose_election import (
    fallback_at_a_glance,
    fallback_currently,
    ranked_at_a_glance_candidates,
    select_at_a_glance_pool,
    select_currently_pool,
)
from pipeline.generate.draft.prose_gate import prose_gate_rejects, prose_gate_violations
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    lint_at_a_glance,
    lint_currently,
    trim_words,
)
from pipeline.generate.draft.prose_synthesis import (
    FIELD_STATUS_NO_EVIDENCE,
    FIELD_STATUS_OFFLINE_FALLBACK,
    FIELD_STATUS_OK,
    FIELD_STATUS_SYNTHESIS_FAILED,
    _evidence_snippets,
    llm_synthesis_active,
    synthesize_at_a_glance,
    synthesize_card_summary,
    synthesize_currently,
    synthesize_questline_cta_hook,
    synthesize_with_validation,
)
from pipeline.generate.draft.provenance import (
    build_revision_index,
    collect_sources_manifest,
    select_identity_url,
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


def _finalize_at_a_glance(
    *,
    zone_name: str,
    at_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> tuple[str | None, list[str], str]:
    """Zone at_a_glance: synthesize with validation-driven retries, else explicit failure.

    Returns ``(text, used_source_ids, field_status)``. On the live path a field that cannot pass
    validation after retries becomes ``None`` + ``synthesis_failed`` — never a borrowed source
    snippet or a canned template. The offline NO_LLM path keeps the sanctioned deterministic borrow.
    """
    if not at_pool:
        return None, [], FIELD_STATUS_NO_EVIDENCE

    def _reasons(candidate: str) -> list[str]:
        reasons = list(lint_at_a_glance(candidate, zone_name=zone_name))
        reasons.extend(lint_passthrough_fragment(candidate))
        reasons.extend(prose_gate_violations(candidate))
        return reasons

    if not llm_synthesis_active():
        # Offline: synthesize_at_a_glance returns the deterministic borrow; keep the ladder, then
        # walk the remaining candidates in borrow-preference order so a lint-clean lead snippet
        # still ships when the top-ranked snippet reads as past-tense narration.
        text, used = synthesize_at_a_glance(at_pool, max_words=MAX_AT_A_GLANCE_WORDS)
        if not _reasons(text):
            return text, used, FIELD_STATUS_OFFLINE_FALLBACK
        text, used = fallback_at_a_glance(at_pool)
        if not _reasons(text):
            return text, used, FIELD_STATUS_OFFLINE_FALLBACK
        for candidate in ranked_at_a_glance_candidates(at_pool)[1:]:
            text = trim_words(
                clean_wiki_snippet(str(candidate.get("snippet", ""))), MAX_AT_A_GLANCE_WORDS
            )
            if text and not _reasons(text):
                source_id = str(candidate.get("source_id", "")).strip()
                return text, [source_id] if source_id else [], FIELD_STATUS_OFFLINE_FALLBACK
        return None, [], FIELD_STATUS_SYNTHESIS_FAILED

    def _call(reinforce: str) -> dict[str, Any]:
        text, used = synthesize_at_a_glance(
            at_pool, max_words=MAX_AT_A_GLANCE_WORDS, reinforce=reinforce
        )
        return {"text": text, "used": used}

    result = synthesize_with_validation(
        call=_call,
        extract_bodies=lambda payload: [str(payload.get("text", ""))],
        validate=lambda payload: _reasons(str(payload.get("text", ""))),
        # Citation shortfall is a soft retry reason (Slice 7): re-prompt for honest citations,
        # never fail the field or fabricate pointers over it.
        validate_soft=lambda payload: citation_shortfall_reasons(
            text=str(payload.get("text", "")),
            used_ids=list(payload.get("used", [])),
            pool=at_pool,
        ),
        source_snippets=_evidence_snippets(at_pool),
        label="at_a_glance",
    )
    if not result.ok:
        return None, [], FIELD_STATUS_SYNTHESIS_FAILED
    return (
        str(result.payload.get("text", "")),
        list(result.payload.get("used", [])),
        FIELD_STATUS_OK,
    )


def _finalize_currently(
    *,
    zone_name: str,
    at_a_glance: str,
    currently_pool: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    pools: dict[str, list[dict[str, Any]]],
) -> tuple[str | None, list[str], str]:
    """Zone currently: synthesize with validation-driven retries, else explicit failure."""
    pool = currently_pool or select_currently_pool(pools, zone_name=zone_name)
    if not pool:
        return None, [], FIELD_STATUS_NO_EVIDENCE
    budget = ZONE_PAGE_BUDGET_RULES["currently"]

    def _reasons(candidate: str) -> list[str]:
        reasons = list(lint_currently(candidate, zone_name=zone_name, at_a_glance=at_a_glance))
        reasons.extend(prose_gate_violations(candidate))
        return reasons

    def _live_reasons(candidate: str) -> list[str]:
        # Word budget as a retry trigger (Slice 2): validate hard-fails outside the rule, so
        # an out-of-budget draft must be repaired by the driver, never shipped. Live-only:
        # the offline borrow ladder has no retry lever, and a thin sanctioned borrow beats a
        # null field on a smoke run (validate still reports the violation on its artifacts).
        reasons = _reasons(candidate)
        words = _word_count(candidate)
        if words < budget.min_words or words > budget.max_words:
            reasons.append(
                f"currently is {words} words; it must be {budget.min_words}-{budget.max_words} "
                "words — expand it with evidenced present-state detail or condense it"
            )
        return reasons

    if not llm_synthesis_active():
        text, used = synthesize_currently(pool, max_words=budget.max_words)
        if _reasons(text):
            text, used = fallback_currently(pool)
            if _reasons(text):
                return None, [], FIELD_STATUS_SYNTHESIS_FAILED
        return text, used, FIELD_STATUS_OFFLINE_FALLBACK

    def _call(reinforce: str) -> dict[str, Any]:
        text, used = synthesize_currently(pool, max_words=budget.max_words, reinforce=reinforce)
        return {"text": text, "used": used}

    result = synthesize_with_validation(
        call=_call,
        extract_bodies=lambda payload: [str(payload.get("text", ""))],
        validate=lambda payload: _live_reasons(str(payload.get("text", ""))),
        # Citation shortfall is a soft retry reason (Slice 7); see _finalize_at_a_glance.
        validate_soft=lambda payload: citation_shortfall_reasons(
            text=str(payload.get("text", "")),
            used_ids=list(payload.get("used", [])),
            pool=pool,
        ),
        source_snippets=_evidence_snippets(pool),
        label="currently",
    )
    if not result.ok:
        return None, [], FIELD_STATUS_SYNTHESIS_FAILED
    return (
        str(result.payload.get("text", "")),
        list(result.payload.get("used", [])),
        FIELD_STATUS_OK,
    )


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


def build_zone_page(
    fact_pack: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    questline_rows: list[dict[str, Any]],
    location_selection_decisions: list[dict[str, Any]],
    instance_rows: list[dict[str, Any]],
    _location_selection_metadata: dict[str, dict[str, Any]],
    location_decision_map: dict[str, dict[str, Any]],
    questline_decision: dict[str, Any] | None,
    *,
    questline_card_metadata: dict[str, dict[str, Any]] | None = None,
    included_cluster_ids: list[str] | None = None,
    faction_profile_targets: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    quest_descriptions_by_node: dict[str, str] | None = None,
    instance_summary_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    zone_id = str(fact_pack.get("entity_id", "zone-unknown"))
    name = str(fact_pack.get("name", zone_id))
    revision_map, source_urls = build_revision_index(fact_pack, snapshots)
    source_url = select_identity_url(source_urls, name)
    pools = _build_evidence_pools(evidence_rows)
    used_source_ids: set[str] = set()

    at_pool = select_at_a_glance_pool(pools["at_a_glance_pool"])
    currently_pool = select_currently_pool(pools, zone_name=name)
    # Raw routed history pool stays the coverage pool (claim-level setup-bridge planning); the
    # synthesis pool is consolidated to paragraphs before select_history_pool's word-count gate.
    history_pool = pools["history_pool"]
    draft_history_pool, max_history = prepare_history_synthesis_pool(history_pool)

    field_status: dict[str, str] = {}
    at_a_glance, at_glance_used, field_status["at_a_glance"] = _finalize_at_a_glance(
        zone_name=name,
        at_pool=at_pool,
        evidence_rows=evidence_rows,
    )

    currently, currently_used, field_status["currently"] = _finalize_currently(
        zone_name=name,
        at_a_glance=at_a_glance or "",
        currently_pool=currently_pool,
        evidence_rows=evidence_rows,
        pools=pools,
    )

    # Pointers come only from the evidence the synthesis reported using — a shortfall against the
    # per-length recommendation is retried as a citation reason and otherwise ships short with a
    # validate WARN (Slice 7); pointers are never fabricated to satisfy a count.
    at_glance_pool = at_pool or pools["at_a_glance_pool"]
    at_a_glance_pointers = _cap_card_pointers(
        _pointers_for_evidence_ids(at_glance_pool, at_glance_used, revision_map),
        max_count=3,
    )
    if at_a_glance is None:
        at_a_glance_pointers = []
    currently_pointer_pool = currently_pool or pools["currently_pool"]
    currently_pointers = _cap_card_pointers(
        _pointers_for_evidence_ids(currently_pointer_pool, currently_used, revision_map),
        max_count=3,
    )
    if currently is None:
        currently_pointers = []
    for pointer in at_a_glance_pointers + currently_pointers:
        used_source_ids.add(pointer["source_id"])

    section_coverage_decisions: list[dict[str, Any]] = []
    history_sections, history_used, field_status["history"] = _finalize_history_sections(
        history_pool=draft_history_pool,
        evidence_rows=evidence_rows,
        max_history=max_history,
        coverage_pool=history_pool,
        subject_id=zone_id,
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
    history_pointer_pool = draft_history_pool or history_pool or pools["history_pool"]
    history_pointers = _pointers_for_evidence_ids(history_pointer_pool, history_used, revision_map)
    if not history_pointers:
        history_pointers = _history_pointers_from_sections(history_sections)
    history_pointers = _cap_card_pointers(history_pointers, max_count=3)
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
        quests = cluster.get("quests", [])
        if not isinstance(quests, list) or not quests:
            continue
        cluster_title = _sanitize_cluster_title(
            str(cluster.get("cluster_title", "Main storylines")),
            zone_name=name,
        )
        card_meta = (questline_card_metadata or {}).get(cluster_id, {})
        if questline_card_metadata is not None and not card_meta:
            raise ValueError(
                f"zone draft reader: selected cluster {cluster_id!r} has no questline metadata "
                "from discovery.questline_card_polish"
            )
        if card_meta:
            cluster_title = render_questline_title(card_meta)
            faction = str(card_meta["faction"]).strip()
            start_anchor = str(card_meta["start_anchor"]).strip()
            chain_refs = [str(ref) for ref in card_meta["chain_refs"] if str(ref).strip()]
            overflow_refs = [
                str(ref) for ref in card_meta.get("overflow_chain_refs", []) if str(ref).strip()
            ]
            quest_by_node = {
                str(row.get("node_id", "")).strip(): row
                for row in quests
                if isinstance(row, dict) and str(row.get("node_id", "")).strip()
            }
            missing_refs = [ref for ref in chain_refs + overflow_refs if ref not in quest_by_node]
            if missing_refs:
                raise ValueError(
                    f"zone draft reader: metadata for {cluster_id!r} references quest graph nodes "
                    f"not present in the selected cluster: {missing_refs}"
                )
            quests = [quest_by_node[ref] for ref in chain_refs + overflow_refs]
        else:
            faction = _majority_faction(
                [str(row.get("faction_binding", "shared")) for row in quests if isinstance(row, dict)]
            )
            first_quest = quests[0] if isinstance(quests[0], dict) else {}
            start_anchor = str(first_quest.get("title", cluster_title))
            chain_refs = [
                str(row.get("node_id", ""))
                for row in quests
                if isinstance(row, dict) and row.get("node_id")
            ]
            overflow_refs = []
        # A graph component may inherit its parent zone as a title. That is a routing label,
        # not a questline subject; use the graph-resolved entry anchor instead.
        if _sanitize_cluster_title(cluster_title, zone_name=name) == "Main storylines":
            cluster_title = start_anchor or "Main storylines"
        card_id_override = str(card_meta.get("card_id", "")).strip()
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
            quest_descriptions=quest_descriptions_by_node,
            max_words=35,
        )
        if not cta or prose_gate_rejects(cta):
            cta = _best_snippet_for_term(scoped_pool, cluster_title, min_words=8) or (
                f"Follow the {cluster_title} arc through its linked quests."
            )
        if not card_meta:
            primary_refs, overflow_refs = _split_chain_refs(chain_refs)
        else:
            primary_refs = chain_refs
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
            cluster_decision=None,
            card_id=card_id_override,
        )
        emitted_cards += 1
        if overflow_refs:
            overflow_pool = _cluster_lore_pool(pools, cluster_id)
            overflow_pool = _faction_scoped_lore_pool(overflow_pool, quests, faction)
            overflow_cta, overflow_used = synthesize_card_summary(
                overflow_pool,
                subject=f"{cluster_title} (continued)",
                max_words=35,
                faction=faction,
            )
            if not overflow_cta:
                overflow_cta = (
                    f"Continue the {cluster_title} arc through its remaining linked quests."
                )
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
                    card_suffix="-segment-2",
                    zone_name=name,
                    cluster_decision=None,
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
        location_selection_decisions=location_selection_decisions,
        location_decision_map=location_decision_map,
        pools=pools,
        revision_map=revision_map,
    )
    for pointers in landmark_provenance_map.values():
        for pointer in pointers:
            used_source_ids.add(pointer["source_id"])

    instance_links: list[dict[str, Any]] = []
    instance_provenance_map: dict[str, list[dict[str, str]]] = {}
    for candidate in _instance_link_candidates(zone_id, instance_rows):
        instance_name = str(candidate.get("name", "")).strip()
        instance_id = str(candidate.get("id", "")).strip()
        scoped = [
            item
            for item in pools["instance_pool"]
            if instance_name.lower() in str(item.get("snippet", "")).lower()
        ] or pools["instance_pool"]
        summary = ""
        used_ids: list[str] = []
        if instance_summary_map and instance_id in instance_summary_map:
            summary = trim_instance_link_summary(str(instance_summary_map[instance_id]))
            used_ids = [
                str(item.get("source_id", "")).strip()
                for item in scoped
                if str(item.get("source_id", "")).strip()
            ]
        if not summary:
            summary, used_ids = synthesize_card_summary(
                scoped, subject=instance_name, max_words=MAX_INSTANCE_LINK_WORDS
            )
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
        pointers = _cap_card_pointers(_pointers_for_evidence_ids(scoped, used_ids, revision_map))
        if pointers:
            instance_provenance_map[str(card["id"])] = pointers
            for pointer in pointers:
                used_source_ids.add(pointer["source_id"])

    # The faction-summary zone-anchor lint accepts the zone name or a subregion token. When the
    # evidence carries no "maps/subregion/geography" section, extract_subregion_tokens yields nothing
    # and the lint effectively demands the literal zone name — so a faction whose WPL role is framed
    # around a subzone ("the Battle for Andorhal") fails the anchor and its card is dropped even when
    # it ranks first. The zone's own elected location cards ARE its subzones, so they are valid
    # zone-of-record anchors; feed their names in so subzone-framed summaries clear the lint.
    location_subregion_tokens = [
        str(card.get("name", "")).strip()
        for card in location_cards
        if str(card.get("name", "")).strip()
    ]
    faction_cards, faction_provenance_map = build_major_factions(
        zone_id=zone_id,
        zone_name=name,
        evidence_rows=evidence_rows,
        pools=pools,
        questline_rows=active_questline_rows,
        revision_map=revision_map,
        faction_profile_targets=faction_profile_targets,
        extra_subregion_tokens=location_subregion_tokens,
        snapshots=snapshots,
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
        "field_status": field_status,
        "provenance": {
            "at_a_glance": at_a_glance_pointers,
            "currently": currently_pointers,
            "history": history_pointers,
            "major_questlines_alliance": questline_provenance_by_bucket[
                "major_questlines_alliance"
            ],
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
    if section_coverage_decisions:
        page_entity["section_coverage_decisions"] = section_coverage_decisions
    return page_entity
