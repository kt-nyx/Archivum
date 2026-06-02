"""Ingest section-walk tests for Slice I2.5.

The HTML mirrors the MediaWiki ``action=parse`` fragment shape that production
ingest consumes for warcraft.wiki.gg instance pages: no <h1> page title, an
infobox table, a collapsible lead boss list, a "Dungeon denizens" section with a
"Bosses" <ul> and an "Encounters" wikitable, and a bottom navbox. These exercise
list/table capture, chrome-table exclusion, and structured-link role accuracy.
"""

from __future__ import annotations

from pipeline.discovery.instance_bosses import collect_boss_candidates
from pipeline.ingest.fetch_wiki import _extract_sections_and_links

INSTANCE_HTML = """
<table class="infobox darktable"><tbody>
<tr><th>End boss</th><td><a href="/wiki/Loken" title="Loken">Loken</a></td></tr>
<tr><td>INFOBOX_ONLY_SENTINEL</td></tr>
</tbody></table>
<table class="mw-collapsible mw-collapsed"><tbody>
<tr><th>Bosses</th></tr>
<tr><td>
<a href="/wiki/General_Bjarngrim" title="General Bjarngrim">General Bjarngrim</a>
<a href="/wiki/Loken" title="Loken">Loken</a>
</td></tr>
</tbody></table>
<p>The Halls of Lightning is a five-man wing where
<a href="/wiki/Loken" title="Loken">Loken</a> made his last stand.</p>
<h2><span class="mw-headline">Dungeon denizens</span></h2>
<h3><span class="mw-headline">Bosses</span></h3>
<ul>
<li><a href="/wiki/General_Bjarngrim" title="General Bjarngrim">General Bjarngrim</a></li>
<li><a href="/wiki/Volkhan" title="Volkhan">Volkhan</a></li>
<li><a href="/wiki/Ionar" title="Ionar">Ionar</a></li>
<li><a href="/wiki/Loken" title="Loken">Loken</a></li>
</ul>
<h3><span class="mw-headline">Encounters</span></h3>
<table class="darktable"><tbody>
<tr><td><a href="/wiki/General_Bjarngrim" title="General Bjarngrim">General Bjarngrim</a></td>
<td><a href="/wiki/Stormforged_Reaver" title="Stormforged Reaver">Stormforged Reaver</a></td></tr>
</tbody></table>
<h2><span class="mw-headline">External links</span></h2>
<table class="navbox"><tbody><tr><td>
NAVBOX_ONLY_SENTINEL
<a href="/wiki/Ulduar" title="Ulduar">Ulduar</a>
</td></tr></tbody></table>
"""


def _blocks_by_text(sections: list[dict[str, str]], needle: str) -> list[dict[str, str]]:
    return [block for block in sections if needle in block["text"]]


def test_list_items_captured_under_roster_roles() -> None:
    sections, _links, _structured = _extract_sections_and_links(INSTANCE_HTML)
    volkhan = _blocks_by_text(sections, "Volkhan")
    assert volkhan, "expected the <ul> boss list to produce section blocks"
    assert volkhan[0]["section_role"] == "bosses"
    assert volkhan[0]["parent_section_role"] == "dungeon_denizens"


def test_table_cells_captured_under_roster_roles() -> None:
    sections, _links, _structured = _extract_sections_and_links(INSTANCE_HTML)
    reaver = _blocks_by_text(sections, "Stormforged Reaver")
    assert reaver, "expected the Encounters <table> cells to produce section blocks"
    assert reaver[0]["section_role"] == "encounters"
    assert reaver[0]["parent_section_role"] == "dungeon_denizens"


def test_chrome_tables_are_excluded() -> None:
    sections, _links, _structured = _extract_sections_and_links(INSTANCE_HTML)
    all_text = " ".join(block["text"] for block in sections)
    assert "INFOBOX_ONLY_SENTINEL" not in all_text
    assert "NAVBOX_ONLY_SENTINEL" not in all_text


def test_structured_link_keeps_roster_role_despite_earlier_narrative_mention() -> None:
    _sections, _links, structured = _extract_sections_and_links(INSTANCE_HTML)
    loken_roles = {
        row["section_role"]
        for row in structured
        if row.get("href") == "/wiki/Loken"
    }
    # Loken is named in the lead prose and the collapsible, but must also carry a
    # roster role from the Bosses list / Encounters table.
    assert {"bosses", "encounters"} & loken_roles, loken_roles


def test_roster_collector_recovers_table_and_list_bosses() -> None:
    sections, _links, structured = _extract_sections_and_links(INSTANCE_HTML)
    candidates = collect_boss_candidates(
        section_blocks=sections,
        instance_name="Halls of Lightning",
        structured_links=structured,
    )
    names = {candidate.name for candidate in candidates}
    assert {"General Bjarngrim", "Volkhan", "Ionar", "Loken"} <= names, names


def test_stray_h1_does_not_override_lead() -> None:
    html = (
        '<h1 class="firstHeading">Halls of Lightning</h1>'
        "<p>Introductory prose about the instance.</p>"
        '<h2><span class="mw-headline">History</span></h2>'
        "<p>History prose.</p>"
    )
    sections, _links, _structured = _extract_sections_and_links(html)
    intro = _blocks_by_text(sections, "Introductory prose")
    assert intro and intro[0]["section_role"] == "lead"
    assert not any(block["section_role"] == "halls_of_lightning" for block in sections)
