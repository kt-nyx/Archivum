"""Normalize ingest source snapshots into manifest entries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext


def _normalized_priority(value: object) -> int | None:
    if isinstance(value, int):
        return value if 1 <= value <= 10 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if 1 <= parsed <= 10 else None
    return None


def _fallback_priority(row_index: int) -> int:
    """Return deterministic fallback priority within contract range 1..10.

    Row-order modulo 10 is used intentionally, so rows 11+ collide with earlier
    priority buckets while remaining stable across runs.
    """
    return ((row_index - 1) % 10) + 1


def run_normalize_source(context: RunContext, snapshots_path: Path) -> Path:
    """Convert raw snapshots into a normalized source manifest."""
    snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
    manifest_entries: list[dict[str, Any]] = []
    for fallback_priority, source in enumerate(snapshots, start=1):
        priority = _normalized_priority(source.get("priority"))
        resolved_priority = (
            priority if priority is not None else _fallback_priority(fallback_priority)
        )
        source_url = str(source["url"])
        manifest_entries.append(
            {
                "entity_id": source["entity_id"],
                "entity_type": source["entity_type"],
                "slug": source["slug"],
                "name": source["name"],
                "source_id": source["source_id"],
                "source_url": source_url,
                "url": source_url,
                "revision_id": source["revision_id"],
                "captured_at": source["captured_at"],
                "source_class": source.get("source_class", "warcraft_wiki"),
                "priority": resolved_priority,
                "categories": source.get("categories", []),
                "infobox": source.get("infobox", {}),
                "retrieval_mode": source.get("retrieval_mode", "unknown"),
                "selection_version": source.get("selection_version", "unknown"),
                "policy_version": source.get("policy_version", "unknown"),
                "manifest_run_id": source.get("manifest_run_id", "unknown"),
                "parent_zone_id": source.get("parent_zone_id", ""),
                "requested_revision_id": source.get("requested_revision_id", ""),
            }
        )

    stage_dir = context.stage_dir("ingest")
    manifest_path = stage_dir / "source_manifest.json"
    write_json(manifest_path, manifest_entries)
    raw_dir = context.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json((raw_dir / "source_manifest.json"), manifest_entries)
    return manifest_path
