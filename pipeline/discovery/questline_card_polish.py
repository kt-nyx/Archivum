"""Build per-cluster card metadata after significance (Slice D)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.discovery.questline_anchor import (
    ENTRY_QUEST_TITLE_KEYWORDS,
    resolve_cluster_start_anchor,
)
from pipeline.discovery.questline_arc_map import map_cluster_to_card_id

_ALGORITHM_VERSION = "v1-card-polish"


def build_zone_questline_card_metadata(
    *,
    zone_id: str,
    cluster_summaries: list[dict[str, Any]],
    v3_rows: list[dict[str, Any]],
    quest_records: list[dict[str, Any]],
    included_cluster_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return (metadata rows, report metrics)."""
    records_by_node = {
        str(record.get("node_id", "")).strip(): record
        for record in quest_records
        if str(record.get("zone_id", "")).strip() == zone_id and record.get("node_id")
    }
    summaries_by_id = {
        str(summary.get("cluster_id", "")).strip(): summary
        for summary in cluster_summaries
        if str(summary.get("zone_id", "")).strip() == zone_id
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

    metadata_rows: list[dict[str, Any]] = []
    entry_anchor_count = 0

    for cluster_id in included_cluster_ids:
        summary = summaries_by_id.get(cluster_id, {})
        quest_rows = sorted(
            rows_by_cluster.get(cluster_id, []),
            key=lambda row: int(row.get("order_in_cluster", 0) or 0),
        )
        cluster_title = str(summary.get("title", cluster_id))
        faction = str(summary.get("faction", "shared"))
        member_node_ids = [
            str(row.get("node_id", "")).strip()
            for row in quest_rows
            if str(row.get("node_id", "")).strip()
        ]
        start_anchor = resolve_cluster_start_anchor(
            cluster_id=cluster_id,
            ordered_quest_rows=quest_rows,
            records_by_node=records_by_node,
        )
        card_id = map_cluster_to_card_id(cluster_id)
        if any(keyword in start_anchor.lower() for keyword in ENTRY_QUEST_TITLE_KEYWORDS):
            entry_anchor_count += 1
        metadata_rows.append(
            {
                "zone_id": zone_id,
                "cluster_id": cluster_id,
                "card_id": card_id,
                "start_anchor": start_anchor,
                "display_title": cluster_title,
                "faction": faction,
                "ordered_chain_refs": member_node_ids,
                "algorithm_version": _ALGORITHM_VERSION,
            }
        )

    metrics = {
        "card_polish_cluster_count": len(metadata_rows),
        "card_polish_entry_anchor_count": entry_anchor_count,
    }
    return metadata_rows, metrics


def index_card_metadata_by_cluster(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index metadata rows by cluster_id for draft consumption."""
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cluster_id = str(row.get("cluster_id", "")).strip()
        if cluster_id:
            indexed[cluster_id] = row
    return indexed


def load_questline_card_metadata(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    blob = json.loads(path.read_text(encoding="utf-8"))
    rows = blob if isinstance(blob, list) else []
    return index_card_metadata_by_cluster([row for row in rows if isinstance(row, dict)])
