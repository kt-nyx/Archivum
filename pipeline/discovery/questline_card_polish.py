"""Build per-cluster card metadata after significance (Slice D)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pipeline.contracts.models import QuestlineCardMetadata, QuestlineCardMetadataArtifact
from pipeline.discovery.questline_anchor import (
    ENTRY_QUEST_TITLE_KEYWORDS,
    resolve_cluster_start_anchor,
    resolve_cluster_start_anchor_ref,
)
from pipeline.discovery.questline_arc_map import map_cluster_to_card_id

_ALGORITHM_VERSION = "v1-card-polish"
_METADATA_SCHEMA_VERSION = "questline_card_metadata.v1"
_MAX_RENDERED_CHAIN_REFS = 12


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
        if not member_node_ids:
            raise ValueError(
                f"questline_card_metadata producer: selected cluster {cluster_id!r} has no quest graph refs"
            )
        missing_records = [node_id for node_id in member_node_ids if node_id not in records_by_node]
        if missing_records:
            raise ValueError(
                "questline_card_metadata producer: selected cluster "
                f"{cluster_id!r} references missing quest records: {missing_records}"
            )
        start_anchor = resolve_cluster_start_anchor(
            cluster_id=cluster_id,
            ordered_quest_rows=quest_rows,
            records_by_node=records_by_node,
        )
        start_anchor_ref = resolve_cluster_start_anchor_ref(
            cluster_id=cluster_id,
            ordered_quest_rows=quest_rows,
            records_by_node=records_by_node,
        )
        if not start_anchor_ref or start_anchor_ref not in records_by_node:
            raise ValueError(
                "questline_card_metadata producer: selected cluster "
                f"{cluster_id!r} has no resolvable start anchor record"
            )
        card_id = map_cluster_to_card_id(cluster_id)
        if any(keyword in start_anchor.lower() for keyword in ENTRY_QUEST_TITLE_KEYWORDS):
            entry_anchor_count += 1
        source_refs = [
            str(records_by_node[node_id].get("source_link", "")).strip()
            for node_id in member_node_ids
            if str(records_by_node[node_id].get("source_link", "")).strip()
        ]
        metadata = QuestlineCardMetadata(
            metadata_id=f"metadata-{card_id}",
            zone_id=zone_id,
            cluster_id=cluster_id,
            source_arc_id=cluster_id,
            card_id=card_id,
            display_title=cluster_title,
            faction=faction,
            faction_variant=faction if faction in {"alliance", "horde"} else None,
            start_anchor=start_anchor,
            start_anchor_ref=start_anchor_ref,
            chain_refs=member_node_ids[:_MAX_RENDERED_CHAIN_REFS],
            overflow_chain_refs=member_node_ids[_MAX_RENDERED_CHAIN_REFS:],
            source_refs=list(dict.fromkeys(source_refs)),
            evidence_refs=member_node_ids,
            algorithm_version=_ALGORITHM_VERSION,
        )
        metadata_rows.append(metadata.model_dump(mode="json"))

    metrics = {
        "card_polish_cluster_count": len(metadata_rows),
        "card_polish_entry_anchor_count": entry_anchor_count,
    }
    return metadata_rows, metrics


def index_card_metadata_by_cluster(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index metadata rows by cluster_id for draft consumption."""
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = QuestlineCardMetadata.model_validate(row)
        indexed[metadata.cluster_id] = metadata.model_dump(mode="json")
    return indexed


def questline_card_metadata_artifact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Serialize the one versioned discovery-to-draft metadata artifact."""
    return QuestlineCardMetadataArtifact(
        metadata=[QuestlineCardMetadata.model_validate(row) for row in rows]
    ).model_dump(mode="json")


def load_questline_card_metadata(path: Path) -> dict[str, dict[str, Any]]:
    """Load the clean-break metadata artifact, rejecting obsolete list artifacts."""
    if not path.exists():
        raise FileNotFoundError(
            f"questline_card_metadata reader: missing artifact from discovery.questline_card_polish; "
            f"expected schema {_METADATA_SCHEMA_VERSION} at {path}"
        )
    try:
        artifact = QuestlineCardMetadataArtifact.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            "questline_card_metadata reader: expected artifact from "
            f"discovery.questline_card_polish with schema {_METADATA_SCHEMA_VERSION}: {exc}"
        ) from exc
    return index_card_metadata_by_cluster(
        [metadata.model_dump(mode="json") for metadata in artifact.metadata]
    )
