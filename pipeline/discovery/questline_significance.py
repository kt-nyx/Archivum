"""Per-cluster questline significance scoring, inclusion decisions, and ranking (Slice C)."""

from __future__ import annotations

from typing import Any

from pipeline.contracts.models import (
    ZONE_MAX_TOTAL_QUESTLINE_CARDS,
    ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
    ZONE_MIN_TOTAL_QUESTLINE_CARDS,
)
from pipeline.discovery.location_discovery import name_in_seed_text
from pipeline.discovery.questline_arc_map import (
    load_pilot_questline_registry,
    match_registry_arc_by_membership,
)

_ALGORITHM_VERSION = "v2-questline-structural"

_CRITERIA = (
    "narrative_centrality",
    "presence_breadth",
    "named_cast_significance",
    "consequence_weight",
    "instance_relevance",
    "player_discoverability",
)


def _presence_breadth_score(quest_count: int) -> int:
    if quest_count >= 7:
        return 2
    if quest_count >= 2:
        return 1
    return 0


def _extract_cluster_features(
    summary: dict[str, Any],
    *,
    member_records: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
    seed_text: str,
    storyline_html: str,
) -> dict[str, Any]:
    quest_count = int(summary.get("quest_count", len(member_records)) or 0)
    npcs = {
        str(record.get("start_npc", "")).strip()
        for record in member_records
        if str(record.get("start_npc", "")).strip()
    }
    orgs = set(summary.get("reputation_orgs") or [])
    for record in member_records:
        org = str(record.get("reputation_org", "")).strip()
        if org:
            orgs.add(org)
    has_chain_start = any(
        not list(record.get("previous", [])) and record.get("has_questbox", True)
        for record in member_records
    )
    cluster_order = 0
    if member_rows:
        cluster_order = int(member_rows[0].get("cluster_order", 0) or 0)
    return {
        "quest_count": quest_count,
        "npc_count": len(npcs),
        "org_count": len(orgs),
        "has_chain_start": has_chain_start,
        "cluster_order": cluster_order,
        "seed_mention": name_in_seed_text(str(summary.get("title", "")), seed_text)
        or any(name_in_seed_text(npc, seed_text) for npc in npcs),
        "storyline_html_len": len(storyline_html.strip()),
    }


def _score_criteria(features: dict[str, Any]) -> dict[str, int]:
    """Structural scoring only — no zone-specific keyword tables.

    Signals: chain length (presence/consequence proxies), named cast breadth, whether the
    cluster is named in the zone seed text, reputation-faction anchoring, and a resolvable
    chain start (player discoverability).
    """
    quest_count = int(features.get("quest_count", 0))
    npc_count = int(features.get("npc_count", 0))
    org_count = int(features.get("org_count", 0))

    narrative = 2 if features.get("seed_mention") else (1 if quest_count >= 5 else 0)
    presence = _presence_breadth_score(quest_count)
    named_cast = 2 if npc_count >= 3 else (1 if npc_count >= 1 else 0)
    consequence = 2 if quest_count >= 7 else (1 if quest_count >= 4 else 0)
    # Reputation-faction anchoring stands in for narrative significance (zone-agnostic).
    instance_rel = 1 if org_count >= 1 else 0
    discoverability = 2 if features.get("has_chain_start") else (1 if quest_count >= 2 else 0)

    return {
        "narrative_centrality": narrative,
        "presence_breadth": presence,
        "named_cast_significance": named_cast,
        "consequence_weight": consequence,
        "instance_relevance": instance_rel,
        "player_discoverability": discoverability,
    }


def _score_single_cluster(
    summary: dict[str, Any],
    *,
    member_records: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
    seed_text: str,
    storyline_html: str,
    run_id: str,
    registry_arc_id: str | None,
    has_registry: bool,
) -> dict[str, Any]:
    cluster_id = str(summary.get("cluster_id", "")).strip()
    zone_id = str(summary.get("zone_id", "")).strip()
    faction = str(summary.get("faction", "shared"))
    features = _extract_cluster_features(
        summary,
        member_records=member_records,
        member_rows=member_rows,
        seed_text=seed_text,
        storyline_html=storyline_html,
    )
    criteria = _score_criteria(features)
    inclusion_score = sum(criteria.values())
    score = round(inclusion_score / 11.0, 3)
    feature_payload: dict[str, float | int | str | bool] = {
        "quest_count": int(features.get("quest_count", 0)),
        "npc_count": int(features.get("npc_count", 0)),
        "cluster_order": int(features.get("cluster_order", 0)),
        "seed_mention": bool(features.get("seed_mention")),
        "inclusion_score": inclusion_score,
        "faction": faction,
        "cluster_title": str(summary.get("title", cluster_id)),
        "registry_arc_id": registry_arc_id or "",
    }
    for key, value in criteria.items():
        feature_payload[f"criterion_{key}"] = int(value)

    borderline = None
    if has_registry:
        # Pilot zones: the curated registry (data, not code keywords) is the inclusion
        # oracle. A cluster is included iff its quest membership binds it to an included
        # arc; everything else is dropped. Structural score only drives ranking/cap order.
        if registry_arc_id:
            final_decision = "include"
            reason_codes = ["registry_arc_match", f"arc:{registry_arc_id}"]
        else:
            final_decision = "exclude"
            reason_codes = ["no_registry_arc_match"]
    elif inclusion_score >= ZONE_MIN_QUESTLINE_INCLUSION_SCORE:
        final_decision = "include"
        reason_codes = ["score_threshold_met"]
    elif inclusion_score <= 5:
        final_decision = "exclude"
        reason_codes = ["below_exclusion_threshold"]
    else:
        ruling = "include" if int(features.get("quest_count", 0)) >= 3 else "exclude"
        borderline = {"prompt_class": "questline_inclusion_borderline", "ruling": ruling}
        final_decision = ruling
        reason_codes = ["borderline_adjudicated", f"score_{inclusion_score}"]

    return {
        "subject_id": cluster_id,
        "subject_type": "questline_cluster",
        "run_id": run_id,
        "algorithm_version": _ALGORITHM_VERSION,
        "features": feature_payload,
        "hard_reject": False,
        "hard_reject_reasons": [],
        "score": score,
        "thresholds": {
            "include_min_score": ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
            "borderline_min": 6,
            "borderline_max": 7,
        },
        "borderline_adjudication": borderline,
        "final_decision": final_decision,
        "reason_codes": reason_codes,
        "zone_id": zone_id,
        "cluster_order": int(features.get("cluster_order", 0)),
        "_sort_score": inclusion_score,
    }


def _apply_cap_trim(
    scored: list[dict[str, Any]],
    *,
    max_cards: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    included = [row for row in scored if str(row.get("final_decision", "")) == "include"]
    included.sort(
        key=lambda row: (
            -int(row.get("_sort_score", 0)),
            int((row.get("features") or {}).get("cluster_order", row.get("cluster_order", 0))),
            str(row.get("subject_id", "")),
        )
    )
    kept_ids = [str(row.get("subject_id", "")) for row in included[:max_cards]]
    kept_set = set(kept_ids)
    for row in scored:
        cluster_id = str(row.get("subject_id", ""))
        if str(row.get("final_decision", "")) != "include":
            continue
        if cluster_id in kept_set:
            continue
        row["final_decision"] = "exclude"
        row["reason_codes"] = list(row.get("reason_codes") or []) + [
            "zone_questline_cap_trimming"
        ]
    return scored, kept_ids


def build_zone_questline_set_decision(
    zone_id: str,
    *,
    run_id: str,
    included_count: int,
    cluster_count: int,
) -> dict[str, Any]:
    if included_count >= ZONE_MIN_TOTAL_QUESTLINE_CARDS:
        final_decision = "include"
        reason_codes = ["clusters_included", f"included_count:{included_count}"]
    elif included_count >= 1:
        final_decision = "defer"
        reason_codes = ["insufficient_included_clusters"]
    else:
        final_decision = "exclude"
        reason_codes = ["no_included_clusters"]
    return {
        "subject_id": zone_id,
        "subject_type": "zone_questline_set",
        "run_id": run_id,
        "algorithm_version": _ALGORITHM_VERSION,
        "features": {
            "included_cluster_count": included_count,
            "total_cluster_count": cluster_count,
        },
        "hard_reject": False,
        "hard_reject_reasons": [],
        "score": min(1.0, included_count / max(ZONE_MIN_TOTAL_QUESTLINE_CARDS, 1)),
        "thresholds": {"include_min_clusters": ZONE_MIN_TOTAL_QUESTLINE_CARDS},
        "borderline_adjudication": None,
        "final_decision": final_decision,
        "reason_codes": reason_codes,
    }


def score_zone_questline_clusters(
    *,
    zone_id: str,
    cluster_summaries: list[dict[str, Any]],
    v3_rows: list[dict[str, Any]],
    quest_records: list[dict[str, Any]],
    seed_text: str = "",
    storyline_html: str = "",
    run_id: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (decision_artifacts incl. zone gate, zone_ranking_payload)."""
    records_by_node = {
        str(record.get("node_id", "")).strip(): record
        for record in quest_records
        if str(record.get("zone_id", "")).strip() == zone_id
    }
    rows_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for row in v3_rows:
        if str(row.get("zone_id", "")).strip() != zone_id:
            continue
        if str(row.get("node_type", "")) != "quest":
            continue
        cluster_id = str(row.get("cluster_id", "")).strip()
        if cluster_id:
            rows_by_cluster.setdefault(cluster_id, []).append(row)

    zone_summaries = [
        summary
        for summary in cluster_summaries
        if str(summary.get("zone_id", "")).strip() == zone_id and summary.get("cluster_id")
    ]
    # The curated registry (when present) is the inclusion oracle for this zone: clusters
    # bind to included arcs by quest-membership overlap, not by keyword tables.
    registry = load_pilot_questline_registry(zone_id)
    has_registry = registry is not None

    scored: list[dict[str, Any]] = []
    for summary in zone_summaries:
        cluster_id = str(summary.get("cluster_id", "")).strip()
        node_ids = list(summary.get("quest_node_ids") or [])
        member_records = [
            records_by_node[node_id] for node_id in node_ids if node_id in records_by_node
        ]
        member_rows = sorted(
            rows_by_cluster.get(cluster_id, []),
            key=lambda row: int(row.get("order_in_cluster", 0) or 0),
        )
        matched_arc = match_registry_arc_by_membership(
            node_ids,
            faction=str(summary.get("faction", "shared")),
            registry=registry,
        )
        registry_arc_id = str(matched_arc.get("id", "")).strip() if matched_arc else None
        scored.append(
            _score_single_cluster(
                summary,
                member_records=member_records,
                member_rows=member_rows,
                seed_text=seed_text,
                storyline_html=storyline_html,
                run_id=run_id,
                registry_arc_id=registry_arc_id,
                has_registry=has_registry,
            )
        )

    # One card per registry arc: when several clusters bind to the same included arc
    # (e.g. an entry-breadcrumb fragment plus the main chain both map to the Andorhal
    # campaign), keep only the richest cluster and supersede the rest.
    if has_registry:
        best_by_arc: dict[str, tuple[tuple[int, int], str]] = {}
        for row in scored:
            features = row.get("features") or {}
            arc_id = str(features.get("registry_arc_id", "")).strip()
            if not arc_id or str(row.get("final_decision", "")) != "include":
                continue
            rank_key = (
                int(features.get("quest_count", 0)),
                int(features.get("inclusion_score", 0)),
            )
            current = best_by_arc.get(arc_id)
            if current is None or rank_key > current[0]:
                best_by_arc[arc_id] = (rank_key, str(row.get("subject_id", "")))
        keep_ids = {subject_id for _key, subject_id in best_by_arc.values()}
        for row in scored:
            features = row.get("features") or {}
            arc_id = str(features.get("registry_arc_id", "")).strip()
            if (
                arc_id
                and str(row.get("final_decision", "")) == "include"
                and str(row.get("subject_id", "")) not in keep_ids
            ):
                row["final_decision"] = "exclude"
                row["reason_codes"] = ["superseded_by_richer_arc_cluster", f"arc:{arc_id}"]

    scored, included_ids = _apply_cap_trim(
        scored,
        max_cards=ZONE_MAX_TOTAL_QUESTLINE_CARDS,
    )

    rankings: list[dict[str, Any]] = []
    for rank, cluster_id in enumerate(included_ids, start=1):
        row = next(item for item in scored if str(item.get("subject_id", "")) == cluster_id)
        features = row.get("features") or {}
        rankings.append(
            {
                "cluster_id": cluster_id,
                "rank": rank,
                "inclusion_score": int(features.get("inclusion_score", 0)),
                "final_decision": "include",
                "faction": str(features.get("faction", "shared")),
                "title": str(features.get("cluster_title", cluster_id)),
            }
        )
    for row in scored:
        if str(row.get("subject_id", "")) not in included_ids:
            features = row.get("features") or {}
            rankings.append(
                {
                    "cluster_id": str(row.get("subject_id", "")),
                    "rank": 0,
                    "inclusion_score": int(features.get("inclusion_score", 0)),
                    "final_decision": str(row.get("final_decision", "exclude")),
                    "faction": str(features.get("faction", "shared")),
                    "title": str(features.get("cluster_title", "")),
                }
            )

    for row in scored:
        row.pop("_sort_score", None)
        row.pop("cluster_order", None)
        row.pop("zone_id", None)

    zone_gate = build_zone_questline_set_decision(
        zone_id,
        run_id=run_id,
        included_count=len(included_ids),
        cluster_count=len(zone_summaries),
    )
    ranking_payload = {
        "zone_id": zone_id,
        "included_cluster_ids": included_ids,
        "rankings": rankings,
    }
    return [zone_gate, *scored], ranking_payload


def load_included_cluster_ids_by_zone(rankings_blob: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Parse zone_quest_cluster_rankings.json into zone_id -> ordered cluster ids."""
    by_zone: dict[str, list[str]] = {}
    for row in rankings_blob:
        if not isinstance(row, dict):
            continue
        zone_id = str(row.get("zone_id", "")).strip()
        if not zone_id:
            continue
        by_zone[zone_id] = [str(cluster_id) for cluster_id in row.get("included_cluster_ids") or []]
    return by_zone
