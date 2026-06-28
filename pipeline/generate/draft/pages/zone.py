"""Zone page builder (build_zone_page) and zone-only prose finalizers."""

from __future__ import annotations

from typing import Any

from pipeline.discovery.geography import resolve_parent_continent
from pipeline.generate.draft.instance_link_lint import trim_instance_link_summary
from pipeline.generate.draft.instance_lint import (
    lint_passthrough_fragment,
)
from pipeline.generate.draft.pages.assembly import (
    _attach_history_source_refs,
    _build_evidence_pools,
    _cap_card_pointers,
    _ensure_pointer_count,
    _history_pointers_from_sections,
    _pointer_count_for_words,
    _pointers_for_source_ids,
    _sanitize_cluster_title,
    _source_entries,
    _word_count,
)
from pipeline.generate.draft.pages.cards import (
    _draft_history_pool,
    _finalize_history_sections,
    build_location_cards,
    build_major_factions,
)
from pipeline.generate.draft.pages.questlines import (
    _MAX_CHAIN_REFS,
    _MAX_CLUSTER_CARDS,
    _append_questline_card,
    _cluster_lore_pool,
    _faction_scoped_lore_pool,
    _group_v3_clusters,
    _lead_chain_with_anchor,
    _majority_faction,
    _split_chain_refs,
)
from pipeline.generate.draft.prose_election import (
    fallback_at_a_glance,
    fallback_currently,
    select_at_a_glance_pool,
    select_currently_pool,
    select_history_pool,
)
from pipeline.generate.draft.prose_gate import prose_gate_rejects
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    lint_at_a_glance,
    lint_currently,
)
from pipeline.generate.draft.prose_synthesis import (
    synthesize_at_a_glance,
    synthesize_card_summary,
    synthesize_currently,
    synthesize_questline_cta_hook,
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
) -> tuple[str, list[str]]:
    def _rejected(candidate: str) -> bool:
        return (
            bool(lint_at_a_glance(candidate, zone_name=zone_name))
            or bool(lint_passthrough_fragment(candidate))
            or prose_gate_rejects(candidate)
        )

    text, used = synthesize_at_a_glance(at_pool, max_words=MAX_AT_A_GLANCE_WORDS)
    if _rejected(text):
        text, used = fallback_at_a_glance(at_pool)
        if _rejected(text):
            text, used = "", []
    if not text:
        rescue_pool = at_pool
        text, used = fallback_at_a_glance(rescue_pool)
        if _rejected(text):
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
    if lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance) or prose_gate_rejects(
        text
    ):
        text, used = fallback_currently(currently_pool)
        if lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance) or prose_gate_rejects(
            text
        ):
            text, used = "", []
    if not text:
        rescue_pool = currently_pool or select_currently_pool(pools, zone_name=zone_name)
        text, used = fallback_currently(rescue_pool)
        if lint_currently(text, zone_name=zone_name, at_a_glance=at_a_glance) or prose_gate_rejects(
            text
        ):
            text, used = "", []
    if not text:
        text = (
            f"{zone_name} remains a contested frontier where crusaders and rival factions "
            "continue to clash over ruined strongholds."
        )
        used = []
    return text, used


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
    currently_pointers = _pointers_for_source_ids(
        currently_pointer_pool, currently_used, revision_map
    )
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
        faction = _majority_faction(
            [str(row.get("faction_binding", "shared")) for row in quests if isinstance(row, dict)]
        )
        first_quest = quests[0] if isinstance(quests[0], dict) else {}
        start_anchor = str(card_meta.get("start_anchor", "")).strip() or str(
            first_quest.get("title", cluster_title)
        )
        card_id_override = str(card_meta.get("card_id", "")).strip()
        suppress_continued_card = bool(card_meta.get("suppress_continued_card"))
        quests = _lead_chain_with_anchor(quests, start_anchor)
        # WS-2: when the cluster maps to a registry arc, the registry is the authoritative
        # chain (full membership + canonical order across all fragments of a multi-part arc).
        # Publish it directly so a single cluster fragment can't truncate/misorder the chain;
        # fall back to the cluster's own node order for non-registry (generic) zones.
        registry_chain_refs = [
            str(ref).strip() for ref in card_meta.get("registry_chain_refs", []) if str(ref).strip()
        ]
        registry_wiki_refs = [
            str(ref).strip() for ref in card_meta.get("registry_wiki_refs", []) if str(ref).strip()
        ]
        if registry_chain_refs:
            chain_refs = registry_chain_refs
            wiki_refs = registry_wiki_refs
        else:
            chain_refs = [
                str(row.get("node_id", ""))
                for row in quests
                if isinstance(row, dict) and row.get("node_id")
            ]
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
    return page_entity
