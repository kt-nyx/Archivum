"""Questline cluster grouping, ordering, and card assembly helpers."""

from __future__ import annotations

from typing import Any

from pipeline.contracts.models import ZONE_MAX_TOTAL_QUESTLINE_CARDS
from pipeline.discovery.entity_typing import normalize_title
from pipeline.generate.draft.card_lint import (
    finalize_cta_hook,
    lint_cta_hook,
    strip_zone_name_from_cta,
)
from pipeline.generate.draft.pages.assembly import (
    _cap_card_pointers,
    _ensure_pointer_count,
    _pointers_for_source_ids,
)

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


def _lead_chain_with_anchor(
    quests: list[dict[str, Any]], start_anchor: str
) -> list[dict[str, Any]]:
    """Reorder so the start-anchor quest leads the chain (#9: anchor == chain head).

    No-op when the anchor isn't found among the quests, so a chain whose entry quest is
    not in the cluster keeps its prerequisite order untouched.
    """
    if not start_anchor.strip() or len(quests) < 2:
        return quests
    target = normalize_title(start_anchor)
    for index, quest in enumerate(quests):
        if not isinstance(quest, dict):
            continue
        if normalize_title(str(quest.get("title", ""))) == target:
            if index == 0:
                return quests
            return [quests[index], *quests[:index], *quests[index + 1 :]]
    return quests


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
    # Re-validate the *finalized* hook: the zone-name strip + tail repair run after the
    # pre-strip gate in zone.py, so any residual mid-sentence breakage would otherwise ship
    # unchecked. Fall back to a clean deterministic hook rather than emit broken prose.
    if lint_cta_hook(cta):
        cta = finalize_cta_hook(f"Follow the {cluster_title} arc through its linked quests.")
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
    grouped.sort(
        key=lambda item: (int(item.get("cluster_order", 0)), str(item.get("cluster_id", "")))
    )
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
        item
        for item in pools.get("quest_cluster_lore_pool", [])
        if str(item.get("cluster_id", "")) == cluster_id
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
