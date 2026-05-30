from __future__ import annotations

from pathlib import Path

from pipeline.discovery.storyline_html import parse_storyline_html

WPL_FIXTURE = Path("tests/fixtures/storyline/western_plaguelands_storyline.html")
GENERIC_HANDOFF_FIXTURE = Path("tests/fixtures/storyline/cross_zone_handoff.html")

NAVIGATION_NOISE_TITLES = {
    "lordaeron",
    "eastern kingdoms",
    "hinterlands",
    "western plaguelands quests",
}

WPL_STORYLINE_QUESTS = {
    "the endless flow",
    "scourge first... alliance later",
    "scourge first... horde later",
    "the battle for andorhal",
    "hero's call: western plaguelands!",
    "the battle resumes!",
}


def test_parse_storyline_html_extracts_quest_nodes_with_factions() -> None:
    html = WPL_FIXTURE.read_text(encoding="utf-8")
    rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    quest_rows = [row for row in rows if row["node_type"] == "quest"]
    assert len(quest_rows) == 6
    titles = {row["title"].lower() for row in quest_rows}
    assert WPL_STORYLINE_QUESTS.issubset(titles)
    assert NAVIGATION_NOISE_TITLES.isdisjoint(titles)
    bindings = {row["faction_binding"] for row in quest_rows}
    assert {"alliance", "horde", "neutral", "shared"}.issubset(bindings)
    assert all(row["source_link"].startswith("/wiki/") for row in quest_rows)
    assert all("[15-30]" in str(row.get("level_range", "")) for row in quest_rows)


def test_storyline_icon_parse_maps_faction_icons_to_bindings() -> None:
    html = WPL_FIXTURE.read_text(encoding="utf-8")
    rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    by_title = {row["title"].lower(): row for row in rows if row["node_type"] == "quest"}
    assert by_title["scourge first... alliance later"]["faction_binding"] == "alliance"
    assert by_title["scourge first... horde later"]["faction_binding"] == "horde"
    assert by_title["the battle for andorhal"]["faction_binding"] == "neutral"
    assert by_title["the endless flow"]["faction_binding"] == "shared"
    assert by_title["hero's call: western plaguelands!"]["faction_binding"] == "alliance"


def test_parse_storyline_html_ignores_questlinks_outside_list_items() -> None:
    html = GENERIC_HANDOFF_FIXTURE.read_text(encoding="utf-8")
    rows = parse_storyline_html(
        html,
        zone_id="zone-example",
        zone_name="Example Zone",
    )
    titles = {row["title"].lower() for row in rows if row["node_type"] == "quest"}
    assert titles == {"quest alpha", "quest beta"}


def test_parse_storyline_html_wpl_prose_questlink_is_excluded() -> None:
    html = WPL_FIXTURE.read_text(encoding="utf-8")
    rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    titles = {row["title"].lower() for row in rows if row["node_type"] == "quest"}
    assert "into the woods" not in titles


def test_parse_storyline_html_wpl_assigns_distinct_cluster_ids() -> None:
    html = WPL_FIXTURE.read_text(encoding="utf-8")
    rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    cluster_ids = {row["cluster_id"] for row in rows if row["node_type"] == "quest"}
    assert len(cluster_ids) >= 2
    orders_by_cluster: dict[str, list[int]] = {}
    for row in rows:
        if row["node_type"] != "quest":
            continue
        orders_by_cluster.setdefault(row["cluster_id"], []).append(row["order_in_cluster"])
    for orders in orders_by_cluster.values():
        assert orders == list(range(1, len(orders) + 1))


def test_parse_storyline_html_wikitable_heading_assigns_cluster() -> None:
    html = """
<table>
<tr><th>Chapter One - Ruined Outpost</th></tr>
</table>
<ul>
<li><span class="questlink"><span class="questlong-prefix linkicon"><img alt="A" src="/images/Alliance_15.png" width="15" height="15" />&#160;[15-30]&#160;</span><a href="/wiki/Quest_Alpha" title="Quest Alpha"><span class="ajaxttlink questlink">Quest Alpha</span></a></span></li>
</ul>
"""
    rows = parse_storyline_html(html, zone_id="zone-example", zone_name="Example Zone")
    assert len(rows) == 1
    assert rows[0]["cluster_id"] == "chapter-one-ruined-outpost"
    assert rows[0]["order_in_cluster"] == 1


def test_parse_storyline_html_empty_when_no_questlink_rows() -> None:
    html = "<html><body><p>No quest table here.</p></body></html>"
    rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    assert rows == []
