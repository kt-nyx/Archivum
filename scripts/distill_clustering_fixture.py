#!/usr/bin/env python3
"""Regenerate the WPL clustering fixture from a real pipeline run.

The clustering test fixtures (`tests/fixtures/clustering/`) used to be hand-authored and
synthetic (21 quests, rep-org simplified, ``start_location`` hand-set), which let the
clusterer test pass while the live run was wrong. This script distills the fixture from the
real discovery artifacts of a completed run so the test exercises the actual quest universe,
chains, factions and reputation orgs.

Inputs (from ``--run-dir``):
  * ``data/discovery/quest_records.jsonl`` -> the per-quest chains/faction/org records.
  * ``data/discovery/zone_quest_graph_v3.json`` -> the roster node universe + order.

The roster's ``cluster_id`` carries the *storyline-section* signal in production, but the
on-disk v3 graph stores the clusterer's own (currently buggy) output there, so we reset it to
the ``unclustered`` placeholder: the fixture exercises chain-based clustering only, matching
the prior fixture's convention. ``description`` is blanked (the clusterer never reads it) to
keep the fixture lean.

Usage:
    python scripts/distill_clustering_fixture.py \
        --run-dir artifacts/runs/test-run-wpl-1 \
        --zone-id zone-western-plaguelands
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Record fields the fixture keeps (superset of what the clusterer reads, matching the prior
# fixture schema). description is retained as a key but blanked; the clusterer ignores it.
_RECORD_FIELDS = (
    "zone_id",
    "node_id",
    "quest_title",
    "source_link",
    "has_questbox",
    "faction",
    "previous",
    "next",
    "reputation_org",
    "category",
    "start_location",
    "description",
)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _distill_records(records: list[dict], zone_id: str) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        if str(rec.get("zone_id", "")) != zone_id:
            continue
        row = {field: rec.get(field) for field in _RECORD_FIELDS}
        row["description"] = ""  # unused by the clusterer; keep the fixture lean
        out.append(row)
    out.sort(key=lambda r: str(r.get("node_id", "")))
    return out


def _distill_roster(graph_rows: list[dict], zone_id: str) -> list[dict]:
    out: list[dict] = []
    for row in graph_rows:
        if str(row.get("zone_id", "")) != zone_id or str(row.get("node_type", "")) != "quest":
            continue
        out.append(
            {
                "zone_id": zone_id,
                "node_type": "quest",
                # Reset the clusterer's own output; the fixture tests chain-based clustering.
                "cluster_id": "unclustered",
                "cluster_title": "",
                "cluster_order": 0,
                "order_in_cluster": int(row.get("order_in_cluster", 0) or 0),
                "node_id": str(row.get("node_id", "")),
                "title": str(row.get("title", "")),
                "faction_binding": str(row.get("faction_binding", "shared")),
                "level_range": str(row.get("level_range", "")),
                "source_link": str(row.get("source_link", "")),
            }
        )
    out.sort(key=lambda r: (int(r.get("order_in_cluster", 0) or 0), str(r.get("node_id", ""))))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--zone-id", default="zone-western-plaguelands")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("tests/fixtures/clustering"), help="fixture output dir"
    )
    args = parser.parse_args()

    discovery = args.run_dir / "data" / "discovery"
    records = _distill_records(_load_jsonl(discovery / "quest_records.jsonl"), args.zone_id)
    graph_rows = json.loads((discovery / "zone_quest_graph_v3.json").read_text(encoding="utf-8"))
    roster = _distill_roster(graph_rows, args.zone_id)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records_path = args.out_dir / "western_plaguelands_quest_records.jsonl"
    roster_path = args.out_dir / "western_plaguelands_roster_v3.json"
    records_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )
    roster_path.write_text(
        json.dumps(roster, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"wrote {len(records)} records -> {records_path}")
    print(f"wrote {len(roster)} roster rows -> {roster_path}")


if __name__ == "__main__":
    main()
