from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.discovery.enrich import run_discovery_enrich
from pipeline.discovery.storyline_html import parse_storyline_html
from pipeline.discovery.workflow import run_discovery_workflow
from pipeline.ingest.traverse_wiki import run_traverse_quests, run_traverse_seed

STORYLINE_HTML = Path("tests/fixtures/storyline/western_plaguelands_storyline.html").read_text(encoding="utf-8")
ZONE_ID = "zone-example"
ZONE_NAME = "Example Zone"
DENYLIST_LINKS = {
    "/wiki/Lordaeron",
    "/wiki/Eastern_Kingdoms",
    "/wiki/Hinterlands",
    "/wiki/Western_Plaguelands_Quests",
}


def _write_ingest_fixtures(context, ingest_dir: Path) -> None:
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
    manifest = [
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
    ]
    (ingest_dir / "source_snapshots.json").write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    (ingest_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_traverse_fetches_v3_quests_from_graph_not_wiki_link_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-traverse", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    _write_ingest_fixtures(context, ingest_dir)
    manifest_path = ingest_dir / "source_manifest.json"
    run_discovery_workflow(context, manifest_path)

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
            "Quest page body with narrative description about the front lines.",
            "mw:100",
            "section:lead paragraph:1",
            [
                {"section_role": "description", "text": "Quest narrative description about the front lines."},
            ],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.traverse_wiki._fetch_url_text", fake_fetch)
    run_traverse_seed(context)
    run_discovery_enrich(context, manifest_path, phase="graph_only")
    run_traverse_quests(context)

    report_path = context.data_dir / "ingest" / "traversal_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    quest_entries = [
        row
        for row in report.get("entries", [])
        if row.get("role") == "quest" and row.get("status") == "fetched"
    ]
    assert quest_entries
    assert all(row.get("traversal_origin") in {"v3_graph", "hub_resolved"} for row in quest_entries)
    fetched_quest_links = {row.get("link", "") for row in quest_entries}
    assert DENYLIST_LINKS.isdisjoint(fetched_quest_links)
    assert any("The_Endless_Flow" in url for url in fetched_urls)
    assert not any("Into_the_Woods" in url for url in fetched_urls)

    merged = json.loads((ingest_dir / "source_snapshots.json").read_text(encoding="utf-8"))
    storyline_snapshots = [row for row in merged if row.get("auxiliary_role") == "storyline"]
    assert storyline_snapshots
    assert storyline_snapshots[0].get("parse_html")

    v3_rows = json.loads((context.data_dir / "discovery" / "zone_quest_graph_v3.json").read_text(encoding="utf-8"))
    parsed = parse_storyline_html(STORYLINE_HTML, zone_id=ZONE_ID, zone_name=ZONE_NAME)
    assert {row["source_link"] for row in parsed if row.get("node_type") == "quest"}.issubset(
        {row.get("link") for row in quest_entries}
    )
    assert len(v3_rows) >= len(parsed)


def test_traverse_resolves_hub_children_from_wiki_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-traverse-hub", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    _write_ingest_fixtures(context, ingest_dir)
    manifest_path = ingest_dir / "source_manifest.json"
    run_discovery_workflow(context, manifest_path)

    def fake_fetch(url: str, source_class: str):
        if "storyline" in url.lower():
            return (
                "Storyline page body",
                "mw:99",
                "section:lead paragraph:1",
                [{"section_role": "part_1", "text": "Part 1"}],
                ["/wiki/The_Endless_Flow"],
                [{"href": "/wiki/The_Endless_Flow", "section_role": "part_1", "label": "The Endless Flow"}],
                STORYLINE_HTML,
            )
        if "Quest_Hub" in url:
            return (
                "Hub disambiguation page.",
                "mw:101",
                "section:lead paragraph:1",
                [{"section_role": "other", "text": "This quest chain splits into two linked paths."}],
                ["/wiki/Quest_Alpha", "/wiki/Quest_Beta"],
                [
                    {"href": "/wiki/Quest_Alpha", "section_role": "other", "label": "Quest Alpha"},
                    {"href": "/wiki/Quest_Beta", "section_role": "other", "label": "Quest Beta"},
                ],
                "",
            )
        return (
            "Quest page body with narrative description about the front lines.",
            "mw:100",
            "section:lead paragraph:1",
            [
                {"section_role": "description", "text": "Quest narrative description about the front lines."},
            ],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.traverse_wiki._fetch_url_text", fake_fetch)
    run_traverse_seed(context)
    run_discovery_enrich(context, manifest_path, phase="graph_only")

    v3_path = context.data_dir / "discovery" / "zone_quest_graph_v3.json"
    v3_rows = json.loads(v3_path.read_text(encoding="utf-8"))
    hub_node = {
        "zone_id": ZONE_ID,
        "node_type": "quest",
        "cluster_id": "part-hub",
        "cluster_title": "Hub Arc",
        "cluster_order": 0,
        "order_in_cluster": 1,
        "node_id": "quest-hub",
        "title": "Quest Hub",
        "source_link": "/wiki/Quest_Hub",
        "faction_binding": "shared",
    }
    v3_path.write_text(json.dumps([hub_node] + v3_rows, indent=2), encoding="utf-8")

    run_traverse_quests(context)

    report = json.loads((context.data_dir / "ingest" / "traversal_report.json").read_text(encoding="utf-8"))
    hub_children = [
        row
        for row in report.get("entries", [])
        if row.get("role") == "quest"
        and row.get("status") == "fetched"
        and row.get("traversal_origin") == "hub_resolved"
    ]
    assert hub_children
    assert all(row.get("hub_resolved_from") == "/wiki/Quest_Hub" for row in hub_children)
    child_links = {row.get("link", "") for row in hub_children}
    assert "/wiki/Quest_Alpha" in child_links
    assert "/wiki/Quest_Beta" in child_links


def test_traverse_skips_defer_location_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-traverse-location-defer", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    _write_ingest_fixtures(context, ingest_dir)
    discovery_dir = context.data_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    (discovery_dir / "location_profile_targets.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": ZONE_ID,
                    "location_id": "location-include",
                    "name": "Include Hold",
                    "source_link": "/wiki/Include_Hold",
                    "source_section_role": "maps_subregions",
                },
                {
                    "zone_id": ZONE_ID,
                    "location_id": "location-defer",
                    "name": "Defer Hold",
                    "source_link": "/wiki/Defer_Hold",
                    "source_section_role": "maps_subregions",
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    decisions_dir = context.data_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "location_significance_decisions.json").write_text(
        json.dumps(
            [
                {"subject_id": "location-include", "final_decision": "include"},
                {"subject_id": "location-defer", "final_decision": "defer"},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    fetched_urls: list[str] = []

    def fake_fetch(url: str, source_class: str):
        fetched_urls.append(url)
        return (
            "Location profile body with enough narrative detail for enrichment.",
            "mw:200",
            "section:lead paragraph:1",
            [{"section_role": "lead", "text": "Location profile body."}],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.traverse_wiki._fetch_url_text", fake_fetch)
    run_traverse_seed(context)

    assert any("Include_Hold" in url for url in fetched_urls)
    assert not any("Defer_Hold" in url for url in fetched_urls)


def test_traverse_fetches_linked_lore_page_not_instance_page_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-instance-lore", artifacts_root=tmp_path / "runs")
    ingest_dir = context.stage_dir("ingest")
    instance_id = "instance-example-dungeon"
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
            "section_blocks": [],
            "wiki_links": [],
            "structured_links": [],
            "retrieval_mode": "live",
            "selection_version": "v1",
            "policy_version": "v1",
            "manifest_run_id": "run-v1",
            "parent_zone_id": "",
            "requested_revision_id": "",
            "priority": 1,
        },
        {
            "entity_id": instance_id,
            "entity_type": "instance",
            "slug": "example-dungeon",
            "name": "Example Dungeon",
            "source_id": "src-instance",
            "source_class": "warcraft_wiki",
            "url": "https://warcraft.wiki.gg/wiki/Example_Dungeon",
            "revision_id": "mw:2",
            "captured_at": "2026-01-01T00:00:00Z",
            "locator": "section:lead paragraph:1",
            "body": "Instance body",
            "section_blocks": [],
            "wiki_links": [],
            "structured_links": [],
            "retrieval_mode": "live",
            "selection_version": "v1",
            "policy_version": "v1",
            "manifest_run_id": "run-v1",
            "parent_zone_id": ZONE_ID,
            "requested_revision_id": "",
            "priority": 1,
        },
    ]
    manifest = [
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
        },
        {
            "entity_id": instance_id,
            "entity_type": "instance",
            "slug": "example-dungeon",
            "name": "Example Dungeon",
            "source_id": "src-instance",
            "source_url": "https://warcraft.wiki.gg/wiki/Example_Dungeon",
            "source_class": "warcraft_wiki",
            "selection_version": "v1",
            "policy_version": "v1",
            "manifest_run_id": "run-v1",
            "parent_zone_id": ZONE_ID,
        },
    ]
    (ingest_dir / "source_snapshots.json").write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    (ingest_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    discovery_dir = context.data_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    (discovery_dir / "instance_lore_source_map.json").write_text(
        json.dumps(
            [
                {
                    "instance_id": instance_id,
                    "lore_source": "linked_lore_page",
                    "source_link": "/wiki/Example_Dungeon_(lore)",
                },
                {
                    "instance_id": "instance-skip-page",
                    "lore_source": "instance_page",
                    "source_link": "/wiki/Example_Dungeon",
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (discovery_dir / "faction_profile_targets.json").write_text("[]", encoding="utf-8")
    (discovery_dir / "location_profile_targets.json").write_text("[]", encoding="utf-8")
    (discovery_dir / "storyline_traversal_targets.json").write_text("[]", encoding="utf-8")
    (context.data_dir / "decisions" / "location_significance_decisions.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (context.data_dir / "decisions" / "location_significance_decisions.json").write_text("[]", encoding="utf-8")

    fetched_urls: list[str] = []

    def fake_fetch(url: str, source_class: str):
        fetched_urls.append(url)
        return (
            "Lore page body with extended narrative history.",
            "mw:300",
            "section:lead paragraph:1",
            [{"section_role": "history", "text": "Extended lore history about the dungeon."}],
            [],
            [],
            "",
        )

    monkeypatch.setattr("pipeline.ingest.traverse_wiki._fetch_url_text", fake_fetch)
    run_traverse_seed(context)

    assert any("Example_Dungeon_(lore)" in url for url in fetched_urls)
    assert not any(url.endswith("/Example_Dungeon") for url in fetched_urls if "(lore)" not in url)
    merged = json.loads((ingest_dir / "source_snapshots.json").read_text(encoding="utf-8"))
    lore_rows = [row for row in merged if row.get("auxiliary_role") == "instance_lore"]
    assert len(lore_rows) == 1
    assert lore_rows[0].get("entity_id") == instance_id
