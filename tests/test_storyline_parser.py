from __future__ import annotations

from pathlib import Path

from pipeline.discovery.storyline_parser import parse_storyline_snapshot


def test_storyline_parser_extracts_parts_and_quest_links() -> None:
    snapshot = {
        "section_blocks": [
            {"section_role": "part_1", "text": "Part 1: The Plaguelands"},
            {"section_role": "part_1", "text": "Introductory quests in the region."},
        ],
        "wiki_links": [
            "/wiki/Quest_A",
            "/wiki/Quest_B",
            "/wiki/Western_Plaguelands_storyline",
        ],
        "structured_links": [],
    }
    v1_rows, v2_rows = parse_storyline_snapshot(
        snapshot,
        zone_id="zone-western-plaguelands",
        cluster_key="questline-western-plaguelands",
    )
    assert any(row["node_type"] == "part_header" for row in v2_rows)
    assert any(row["node_type"] == "quest" for row in v2_rows)
    assert v1_rows
    assert v2_rows[0]["prev_node_id"] is None


def test_storyline_parser_legacy_link_dump_not_used_when_parse_html_present() -> None:
    """When parse_html is available, v3 HTML parser is authoritative (see traverse/enrich)."""
    from pipeline.discovery.storyline_html import parse_storyline_html

    html = Path("tests/fixtures/storyline/western_plaguelands_storyline.html").read_text(
        encoding="utf-8"
    )
    v3_rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    snapshot = {
        "parse_html": html,
        "section_blocks": [{"section_role": "part_1", "text": "Part 1: The Plaguelands"}],
        "wiki_links": [
            "/wiki/Lordaeron",
            "/wiki/Eastern_Kingdoms",
            "/wiki/Western_Plaguelands_storyline",
        ],
        "structured_links": [],
    }
    _v1_rows, v2_rows = parse_storyline_snapshot(
        snapshot,
        zone_id="zone-western-plaguelands",
        cluster_key="questline-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    v3_titles = {row["title"].lower() for row in v3_rows if row.get("node_type") == "quest"}
    assert v3_titles.isdisjoint({"lordaeron", "eastern kingdoms", "hinterlands"})
    assert len(v3_rows) >= 5
    assert "horde" in {row.get("faction_binding") for row in v3_rows}
