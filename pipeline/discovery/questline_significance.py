"""Per-cluster questline significance scoring, inclusion decisions, and ranking (Slice C)."""

from __future__ import annotations

from typing import Any

from pipeline.contracts.models import (
    ZONE_MAX_TOTAL_QUESTLINE_CARDS,
    ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
    ZONE_MIN_TOTAL_QUESTLINE_CARDS,
)
from pipeline.discovery.location_discovery import name_in_seed_text

_ALGORITHM_VERSION = "v1-questline-significance"
_WPL_PILOT_ZONE_ID = "zone-western-plaguelands"
_WPL_PILOT_MAX_CARDS = 4

_CRITERIA = (
    "narrative_centrality",
    "presence_breadth",
    "named_cast_significance",
    "consequence_weight",
    "instance_relevance",
    "player_discoverability",
)

_ANDORHAL_KEYWORDS = frozenset({"andorhal", "warchief", "hero's call", "reckoning", "alas"})
_MENDER_KEYWORDS = frozenset({"mender", "cenarion", "plaguelands restoration", "zen'kiki"})
_HEARTHGLEN_KEYWORDS = frozenset({"hearthglen", "tirion", "fordring", "highlord"})
_NORTHRIDGE_KEYWORDS = frozenset({"northridge", "lumber", "redpine", "gnoll"})
_GAHRRON_KEYWORDS = frozenset({"gahrron", "cauldron", "renewed plague", "withering"})
_INSTANCE_KEYWORDS = frozenset({"scholomancer", "araj", "scholomance"})
_ENTRY_KEYWORDS = frozenset(
    {"hero's call", "warchief's command", "new era for the plaguelands", "audience with the highlord"}
)


def _normalize_blob(*parts: str) -> str:
    return " ".join(part.strip().lower() for part in parts if part.strip())


def _cluster_blob(
    summary: dict[str, Any],
    member_records: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
) -> str:
    title = str(summary.get("title", ""))
    quest_titles = [
        str(record.get("quest_title", "") or row.get("title", ""))
        for record, row in zip(member_records, member_rows, strict=False)
    ]
    locations = [str(record.get("start_location", "")) for record in member_records]
    npcs = [str(record.get("start_npc", "")) for record in member_records]
    return _normalize_blob(title, *quest_titles, *locations, *npcs)


def _presence_breadth_score(quest_count: int) -> int:
    if quest_count >= 7:
        return 2
    if quest_count >= 2:
        return 1
    return 0


def _keyword_hits(blob: str, keywords: frozenset[str]) -> int:
    return sum(1 for keyword in keywords if keyword in blob)


def _extract_cluster_features(
    summary: dict[str, Any],
    *,
    member_records: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
    seed_text: str,
    storyline_html: str,
) -> dict[str, Any]:
    blob = _cluster_blob(summary, member_records, member_rows)
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
        "blob": blob,
        "quest_count": quest_count,
        "npc_count": len(npcs),
        "org_count": len(orgs),
        "has_chain_start": has_chain_start,
        "cluster_order": cluster_order,
        "seed_mention": name_in_seed_text(str(summary.get("title", "")), seed_text)
        or any(name_in_seed_text(npc, seed_text) for npc in npcs),
        "andorhal_hits": _keyword_hits(blob, _ANDORHAL_KEYWORDS),
        "mender_hits": _keyword_hits(blob, _MENDER_KEYWORDS),
        "hearthglen_hits": _keyword_hits(blob, _HEARTHGLEN_KEYWORDS),
        "northridge_hits": _keyword_hits(blob, _NORTHRIDGE_KEYWORDS),
        "gahrron_hits": _keyword_hits(blob, _GAHRRON_KEYWORDS),
        "instance_hits": _keyword_hits(blob, _INSTANCE_KEYWORDS),
        "entry_hits": _keyword_hits(blob, _ENTRY_KEYWORDS),
        "storyline_html_len": len(storyline_html.strip()),
    }


def _hard_reject_reasons(
    features: dict[str, Any],
    *,
    mender_cluster_present: bool,
) -> list[str]:
    blob = str(features.get("blob", ""))
    if features.get("northridge_hits", 0) >= 1 and features.get("andorhal_hits", 0) == 0:
        return ["local_side_content"]
    if (
        features.get("gahrron_hits", 0) >= 1
        and features.get("mender_hits", 0) == 0
        and mender_cluster_present
    ):
        return ["thematic_duplicate_of_menders_stead"]
    if "northridge" in blob and "lumber" in blob and features.get("quest_count", 0) <= 3:
        return ["local_side_content"]
    if features.get("gahrron_hits", 0) >= 2 and mender_cluster_present:
        return ["thematic_duplicate_of_menders_stead"]
    return []


def _score_criteria(features: dict[str, Any]) -> dict[str, int]:
    quest_count = int(features.get("quest_count", 0))
    npc_count = int(features.get("npc_count", 0))
    blob = str(features.get("blob", ""))

    narrative = 0
    if features.get("andorhal_hits", 0) >= 1:
        narrative = 2
    elif features.get("mender_hits", 0) >= 1 or features.get("hearthglen_hits", 0) >= 1:
        narrative = 2
    elif features.get("seed_mention"):
        narrative = 1

    presence = _presence_breadth_score(quest_count)

    named_cast = 0
    if npc_count >= 3:
        named_cast = 2
    elif npc_count >= 1:
        named_cast = 1

    consequence = 0
    if any(token in blob for token in ("reckoning", "alas", "andorhal", "battle for")):
        consequence = 2
    elif features.get("mender_hits", 0) >= 1 or features.get("hearthglen_hits", 0) >= 1:
        consequence = 2
    elif features.get("andorhal_hits", 0) >= 1:
        consequence = 1

    instance_rel = 0
    if features.get("instance_hits", 0) >= 2:
        instance_rel = 2
    elif features.get("instance_hits", 0) >= 1:
        instance_rel = 1

    discoverability = 0
    if features.get("entry_hits", 0) >= 1 or features.get("has_chain_start"):
        discoverability = 2
    elif quest_count >= 2:
        discoverability = 1

    return {
        "narrative_centrality": narrative,
        "presence_breadth": presence,
        "named_cast_significance": named_cast,
        "consequence_weight": consequence,
        "instance_relevance": instance_rel,
        "player_discoverability": discoverability,
    }


def _borderline_ruling(features: dict[str, Any], inclusion_score: int) -> str:
    quest_count = int(features.get("quest_count", 0))
    npc_count = int(features.get("npc_count", 0))
    if inclusion_score >= 7 and quest_count >= 3 and npc_count >= 1:
        return "include"
    if inclusion_score >= 7 and (
        features.get("andorhal_hits", 0) >= 1
        or features.get("mender_hits", 0) >= 1
        or features.get("hearthglen_hits", 0) >= 1
    ):
        return "include"
    if features.get("andorhal_hits", 0) >= 1 or features.get("mender_hits", 0) >= 1:
        return "include"
    return "exclude"


def _score_single_cluster(
    summary: dict[str, Any],
    *,
    member_records: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
    seed_text: str,
    storyline_html: str,
    mender_cluster_present: bool,
    run_id: str,
) -> dict[str, Any]:
    cluster_id = str(summary.get("cluster_id", "")).strip()
    zone_id = str(summary.get("zone_id", "")).strip()
    features = _extract_cluster_features(
        summary,
        member_records=member_records,
        member_rows=member_rows,
        seed_text=seed_text,
        storyline_html=storyline_html,
    )
    hard_reject_reasons = _hard_reject_reasons(features, mender_cluster_present=mender_cluster_present)
    criteria = _score_criteria(features)
    inclusion_score = sum(criteria.values())
    score = round(inclusion_score / 12.0, 3)
    feature_payload: dict[str, float | int | str | bool] = {
        "quest_count": int(features.get("quest_count", 0)),
        "npc_count": int(features.get("npc_count", 0)),
        "cluster_order": int(features.get("cluster_order", 0)),
        "seed_mention": bool(features.get("seed_mention")),
        "inclusion_score": inclusion_score,
        "faction": str(summary.get("faction", "shared")),
        "cluster_title": str(summary.get("title", cluster_id)),
    }
    for key, value in criteria.items():
        feature_payload[f"criterion_{key}"] = int(value)

    if hard_reject_reasons:
        final_decision = "exclude"
        reason_codes = list(hard_reject_reasons)
        borderline = None
    elif inclusion_score >= ZONE_MIN_QUESTLINE_INCLUSION_SCORE:
        final_decision = "include"
        reason_codes = ["score_threshold_met"]
        borderline = None
    elif inclusion_score <= 5:
        final_decision = "exclude"
        reason_codes = ["below_exclusion_threshold"]
        borderline = None
    else:
        borderline = {
            "prompt_class": "questline_inclusion_borderline",
            "ruling": _borderline_ruling(features, inclusion_score),
        }
        final_decision = borderline["ruling"]
        reason_codes = ["borderline_adjudicated", f"score_{inclusion_score}"]

    return {
        "subject_id": cluster_id,
        "subject_type": "questline_cluster",
        "run_id": run_id,
        "algorithm_version": _ALGORITHM_VERSION,
        "features": feature_payload,
        "hard_reject": bool(hard_reject_reasons),
        "hard_reject_reasons": hard_reject_reasons,
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
    zone_id: str,
    max_cards: int,
    pilot_cap: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    included = [row for row in scored if str(row.get("final_decision", "")) == "include"]
    included.sort(
        key=lambda row: (
            -int(row.get("_sort_score", 0)),
            int((row.get("features") or {}).get("cluster_order", row.get("cluster_order", 0))),
            str(row.get("subject_id", "")),
        )
    )
    cap = max_cards
    trim_reason = "zone_questline_cap_trimming"
    if pilot_cap is not None:
        cap = min(cap, pilot_cap)
        trim_reason = "pilot_cap_trimming"
    kept_ids = [str(row.get("subject_id", "")) for row in included[:cap]]
    kept_set = set(kept_ids)
    for row in scored:
        cluster_id = str(row.get("subject_id", ""))
        if str(row.get("final_decision", "")) != "include":
            continue
        if cluster_id in kept_set:
            continue
        row["final_decision"] = "exclude"
        row["reason_codes"] = list(row.get("reason_codes") or []) + [trim_reason]
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
    pilot_max_cards: int | None = None,
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
    mender_present = any(
        _keyword_hits(
            _cluster_blob(
                summary,
                [
                    records_by_node.get(node_id, {})
                    for node_id in summary.get("quest_node_ids", [])
                ],
                rows_by_cluster.get(str(summary.get("cluster_id", "")), []),
            ),
            _MENDER_KEYWORDS,
        )
        >= 1
        for summary in zone_summaries
    )

    scored: list[dict[str, Any]] = []
    for summary in zone_summaries:
        cluster_id = str(summary.get("cluster_id", "")).strip()
        node_ids = list(summary.get("quest_node_ids") or [])
        member_records = [records_by_node[node_id] for node_id in node_ids if node_id in records_by_node]
        member_rows = sorted(
            rows_by_cluster.get(cluster_id, []),
            key=lambda row: int(row.get("order_in_cluster", 0) or 0),
        )
        scored.append(
            _score_single_cluster(
                summary,
                member_records=member_records,
                member_rows=member_rows,
                seed_text=seed_text,
                storyline_html=storyline_html,
                mender_cluster_present=mender_present,
                run_id=run_id,
            )
        )

    effective_pilot_cap = pilot_max_cards
    if zone_id == _WPL_PILOT_ZONE_ID and effective_pilot_cap is None:
        effective_pilot_cap = _WPL_PILOT_MAX_CARDS

    scored, included_ids = _apply_cap_trim(
        scored,
        zone_id=zone_id,
        max_cards=ZONE_MAX_TOTAL_QUESTLINE_CARDS,
        pilot_cap=effective_pilot_cap,
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
