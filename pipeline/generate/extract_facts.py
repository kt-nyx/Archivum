"""Extract normalized fact packs from coalesced entities."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext


def run_extract_facts(
    context: RunContext,
    coalesced_entities_path: Path,
    *,
    max_entity_concurrency: int = 4,
) -> list[Path]:
    """Transform coalesced JSONL entities into structured fact packs."""
    rows = [
        json.loads(line)
        for line in coalesced_entities_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stage_dir = context.data_dir / "extracted"
    stage_dir.mkdir(parents=True, exist_ok=True)

    def _write_row(row: dict[str, Any]) -> Path:
        output_path = stage_dir / f"{row['entity_id']}.json"
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
                f"extract missing source URLs for entity '{row['entity_id']}' source_ids: {joined}"
            )
        fact_pack = {
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
        output_path.write_text(json.dumps(fact_pack, indent=2), encoding="utf-8")
        return output_path

    outputs: list[Path] = []
    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [executor.submit(_write_row, row) for row in rows]
        for future in futures:
            outputs.append(future.result())
    return outputs
