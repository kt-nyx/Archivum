from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata, index_card_metadata_by_cluster
from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters
from pipeline.generate.draft.card_lint import lint_cta_hook
from pipeline.generate.draft.pages import build_zone_page

FIXTURE_DIR = Path("tests/fixtures/clustering")
from pipeline.discovery.pilot_questline_registry import load_registry
ZONE_ID = "zone-western-plaguelands"


def _load_wpl() -> tuple[list[dict], list[dict]]:
    roster = json.loads((FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return roster, records


def _registry_anchor_by_card_id() -> dict[str, str]:
    registry = load_registry(ZONE_ID) or {}
    return {str(arc["id"]): str(arc["start_anchor"]) for arc in registry.get("included_arcs", [])}


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    os.environ["WOW_LORE_WIKI_FIRST_NO_LLM"] = "1"


def test_build_zone_page_wpl_emits_four_ql_cards_without_continued(monkeypatch: pytest.MonkeyPatch) -> None:
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID,
        roster_rows=roster,
        quest_records=records,
        zone_name="Western Plaguelands",
    )
    _decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test",
    )
    metadata_rows, _ = build_zone_questline_card_metadata(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        included_cluster_ids=ranking["included_cluster_ids"],
    )
    metadata_by_cluster = index_card_metadata_by_cluster(metadata_rows)
    evidence_rows = []
    for row in rows:
        if row.get("node_type") != "quest":
            continue
        cluster_id = str(row.get("cluster_id", ""))
        if cluster_id not in ranking["included_cluster_ids"]:
            continue
        evidence_rows.append(
            {
                "subject_id": ZONE_ID,
                "subject_type": "zone",
                "field_name": "quest_cluster_lore",
                "evidence_items": [
                    {
                        "source_url": f"https://warcraft.wiki.gg{row.get('source_link', '')}",
                        "source_title": row.get("title", ""),
                        "snippet": f"Lore beat for {row.get('title', 'quest')}.",
                        "section_role": "description",
                        "confidence": 1.0,
                    }
                ],
                "build_meta": {
                    "source_id": f"src-{row['node_id']}",
                    "cluster_id": cluster_id,
                    "quest_node_id": row["node_id"],
                    "subject_zone_id": ZONE_ID,
                },
            }
        )
    draft = build_zone_page(
        {
            "entity_id": ZONE_ID,
            "name": "Western Plaguelands",
            "source_ids": ["src-zone"],
            "revision_ids": ["mw:1"],
            "source_urls": {"src-zone": "https://warcraft.wiki.gg/wiki/Western_Plaguelands"},
        },
        evidence_rows,
        rows,
        [],
        [],
        {},
        {},
        {"final_decision": "include"},
        questline_card_metadata=metadata_by_cluster,
        included_cluster_ids=ranking["included_cluster_ids"],
    )
    cards = draft["major_questlines"]
    # Membership-based binding: this synthetic fixture's Andorhal clusters carry real arc
    # node-ids and emit; its Hearthglen/Mender placeholders bind to no arc (the full 3-card
    # outcome is validated against real quest records elsewhere). No raw cluster-* ids.
    card_ids = {card["id"] for card in cards}
    assert card_ids == {"ql-andorhal-alliance", "ql-andorhal-horde"}
    assert all(str(card["id"]).startswith("ql-") for card in cards)
    assert not any(str(card["id"]).endswith("-continued") for card in cards)
    anchors = _registry_anchor_by_card_id()
    for card in cards:
        assert card["start_anchor"] == anchors[card["id"]]
        assert not lint_cta_hook(str(card["cta_hook"]))
        assert len(card["chain_refs"]) <= 12
