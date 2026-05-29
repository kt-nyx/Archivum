from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.discovery.workflow import run_discovery_workflow
from pipeline.ingest.traverse_wiki import run_traverse_wiki

STORYLINE_HTML = Path("tests/fixtures/storyline/western_plaguelands_storyline.html").read_text(encoding="utf-8")
ZONE_ID = "zone-example"
ZONE_NAME = "Example Zone"
DENYLIST_LINKS = {
    "/wiki/Lordaeron",
    "/wiki/Eastern_Kingdoms",
    "/wiki/Hinterlands",
    "/wiki/Western_Plaguelands_Quests",
}


def test_traverse_fetches_v3_quests_from_parse_html_not_wiki_link_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-traverse", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    snapshots = [
        {
            "entity_id": ZONE_ID,
            "entity_type": "zone",
            "slug": "example-zone",
            "name": ZONE_NAME,
            "source_id": "src-zone",
            "source_class": "warcraft_wiki",
            "url": "https://warcraft.wiki.gg/wiki/Example_Zone",
            "revision_id": "mw:1",
            "captured_at": "2026-01-01T00:00:00Z",
            "locator": "section:lead paragraph:1",
            "body": "Zone body",
            "section_blocks": [{"section_role": "quests", "text": f"See {ZONE_NAME} storyline"}],
            "wiki_links": [],
            "structured_links": [],
            "retrieval_mode": "live",
            "selection_version": "v1",
            "policy_version": "v1",
            "manifest_run_id": "run-v1",
            "parent_zone_id": "",
            "requested_revision_id": "",
            "priority": 1,
        }
    ]
    (ingest_dir / "source_snapshots.json").write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    (ingest_dir / "source_manifest.json").write_text(
        json.dumps(
            [
                {
                    "entity_id": ZONE_ID,
                    "entity_type": "zone",
                    "slug": "example-zone",
                    "name": ZONE_NAME,
                    "source_id": "src-zone",
                    "source_url": "https://warcraft.wiki.gg/wiki/Example_Zone",
                    "source_class": "warcraft_wiki",
                    "selection_version": "v1",
                    "policy_version": "v1",
                    "manifest_run_id": "run-v1",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    run_discovery_workflow(context, ingest_dir / "source_manifest.json")

    fetched_urls: list[str] = []

    def fake_fetch(url: str, source_class: str):
        fetched_urls.append(url)
        if "storyline" in url.lower():
            return (
                "Storyline page body",
                "mw:99",
                "section:lead paragraph:1",
                [{"section_role": "part_1", "text": "Part 1"}],
                list(DENYLIST_LINKS) + ["/wiki/The_Endless_Flow"],
                [{"href": "/wiki/The_Endless_Flow", "section_role": "part_1", "label": "The Endless Flow"}],
                STORYLINE_HTML,
            )
        return (
            "Quest page body",
            "mw:100",
            "section:lead paragraph:1",
            [{"section_role": "lead", "text": "Quest lead"}],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.traverse_wiki._fetch_url_text", fake_fetch)
    outputs = run_traverse_wiki(context)
    report = json.loads(outputs["traversal_report"].read_text(encoding="utf-8"))
    quest_entries = [
        row for row in report.get("entries", []) if row.get("role") == "quest" and row.get("status") == "fetched"
    ]
    assert quest_entries
    fetched_quest_links = {row.get("link", "") for row in quest_entries}
    assert DENYLIST_LINKS.isdisjoint(fetched_quest_links)
    assert any("The_Endless_Flow" in url for url in fetched_urls)
    assert not any("Into_the_Woods" in url for url in fetched_urls)
    merged = json.loads((ingest_dir / "source_snapshots.json").read_text(encoding="utf-8"))
    storyline_snapshots = [row for row in merged if row.get("auxiliary_role") == "storyline"]
    assert storyline_snapshots
    assert storyline_snapshots[0].get("parse_html")
