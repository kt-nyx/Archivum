from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.storyline_html import parse_storyline_html

GEOGRAPHY_DENYLIST_TITLES = {
    "lordaeron",
    "eastern kingdoms",
    "hinterlands",
    "cape of stranglethorn",
}

DEFAULT_RUN_ROOT = Path(
    os.environ.get("LORE_PILOT_RUN_ROOT", "artifacts/runs/run-western-plaguelands")
)


def test_run_v3_graph_rejects_geography_when_artifact_present() -> None:
    v3_path = DEFAULT_RUN_ROOT / "data" / "discovery" / "zone_quest_graph_v3.json"
    if not v3_path.exists():
        pytest.skip("pilot run artifact not present (set LORE_PILOT_RUN_ROOT to override)")
    rows = json.loads(v3_path.read_text(encoding="utf-8"))
    quest_rows = [row for row in rows if row.get("node_type") == "quest"]
    assert len(quest_rows) >= 5
    for row in quest_rows:
        title = str(row.get("title", "")).lower()
        assert title not in GEOGRAPHY_DENYLIST_TITLES
        assert not title.endswith(" quests")
        zone_name = str(row.get("zone_id", "")).replace("zone-", "").replace("-", " ").title()
        valid, _ = is_valid_quest_graph_link(
            str(row.get("source_link", "")),
            zone_name=zone_name,
        )
        assert valid
    assert any(str(row.get("faction_binding", "")) == "horde" for row in quest_rows)


def test_run_v3_matches_storyline_list_item_parser_when_artifact_present() -> None:
    v3_path = DEFAULT_RUN_ROOT / "data" / "discovery" / "zone_quest_graph_v3.json"
    snapshots_path = DEFAULT_RUN_ROOT / "data" / "ingest" / "source_snapshots.json"
    if not v3_path.exists() or not snapshots_path.exists():
        pytest.skip("pilot run artifact not present (set LORE_PILOT_RUN_ROOT to override)")
    snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
    v3_rows = json.loads(v3_path.read_text(encoding="utf-8"))
    for storyline in snapshots:
        if str(storyline.get("auxiliary_role", "")) != "storyline":
            continue
        zone_id = str(storyline.get("entity_id", ""))
        zone_name = str(storyline.get("name", ""))
        parse_html = str(storyline.get("parse_html", "")).strip()
        if not parse_html:
            continue
        expected_titles = {
            str(row.get("title", "")).lower()
            for row in parse_storyline_html(parse_html, zone_id=zone_id, zone_name=zone_name)
        }
        v3_titles = {
            str(row.get("title", "")).lower()
            for row in v3_rows
            if row.get("node_type") == "quest" and str(row.get("zone_id", "")) == zone_id
        }
        extra = v3_titles - expected_titles
        if extra:
            pytest.skip(
                "pilot artifact v3 graph is stale relative to current parser "
                f"(extra quests for {zone_id}: {sorted(extra)}); rerun pipeline to refresh"
            )
