"""Reshape coalesced entity rows into provenance-complete fact packs.

S6 folded the former standalone Extract stage into coalesce: the fact-pack
transform and the missing-source-URL hard-fail now run at the end of coalesce,
which writes fact packs directly. The output directory keeps the historical
``extracted`` name so downstream draft consumers are unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext


def build_fact_pack(row: dict[str, Any]) -> dict[str, Any]:
    """Reshape a coalesced entity row into a fact pack.

    Enforces that every declared ``source_id`` resolves to a non-empty source
    URL (the integrity guard preserved from the Extract stage).
    """
    source_urls: dict[str, str] = {}
    row_source_urls = row.get("source_urls")
    if isinstance(row_source_urls, dict):
        for source_id, source_url in row_source_urls.items():
            if (
                isinstance(source_id, str)
                and isinstance(source_url, str)
                and source_url.strip()
            ):
                source_urls[source_id] = source_url
    for item in row.get("fact_items", []):
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        source_url = item.get("url")
        if isinstance(source_id, str) and isinstance(source_url, str):
            source_urls[source_id] = source_url
    missing_source_urls = [
        source_id
        for source_id in row["source_ids"]
        if not str(source_urls.get(source_id, "")).strip()
    ]
    if missing_source_urls:
        joined = ", ".join(str(source_id) for source_id in missing_source_urls)
        raise RuntimeError(
            f"coalesce missing source URLs for entity '{row['entity_id']}' source_ids: {joined}"
        )
    return {
        "entity_id": row["entity_id"],
        "entity_type": row["entity_type"],
        "slug": row["slug"],
        "name": row["name"],
        "parent_zone_id": row.get("parent_zone_id", ""),
        "confidence": row["confidence"],
        "claims": [item["claim"] for item in row.get("fact_items", [])],
        "fact_items": row.get("fact_items", []),
        "source_ids": row["source_ids"],
        "revision_ids": row["revision_ids"],
        "source_urls": source_urls,
        "coalesce_mode": row.get("coalesce_mode", "unknown"),
    }


def write_fact_packs(context: RunContext, rows: list[dict[str, Any]]) -> list[Path]:
    """Write one fact pack per coalesced row; raise on any missing source URL."""
    stage_dir = context.data_dir / "extracted"
    stage_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for row in rows:
        fact_pack = build_fact_pack(row)
        output_path = stage_dir / f"{fact_pack['entity_id']}.json"
        write_json(output_path, fact_pack)
        outputs.append(output_path)
    return outputs
