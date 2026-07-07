"""Tests for pipeline.common.wiki_html and the BS4-backed ingest parser (WS-A)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.common import wiki_html
from pipeline.ingest.fetch_wiki import _extract_main_text, _extract_sections_and_links

CASES = json.loads(
    Path("tests/fixtures/wiki_html/ingest_parser_cases.json").read_text(encoding="utf-8")
)


def test_strip_tags_decodes_entities_and_collapses() -> None:
    assert wiki_html.strip_tags("<p>Foo  &amp;  <b>Bar</b></p>") == "Foo & Bar"
    assert wiki_html.strip_tags("") == ""


def test_extract_links_filters_and_dedupes() -> None:
    html = (
        '<a href="/wiki/A">a</a><a href="https://warcraft.wiki.gg/wiki/B">b</a>'
        '<a href="https://example.com/x">x</a><a href="#frag">f</a><a href="/wiki/A">dup</a>'
    )
    assert wiki_html.extract_links(html) == ["/wiki/A", "https://warcraft.wiki.gg/wiki/B"]


def test_content_blocks_handles_nested_table_inside_chrome() -> None:
    # Regression: a chrome table containing a nested table must not crash (decomposing the
    # outer table detaches the inner one mid-iteration) and must drop all chrome content.
    html = (
        '<table class="navbox"><tr><td>'
        "<table><tr><td>NESTED_CHROME</td></tr></table>OUTER_CHROME"
        "</td></tr></table>"
        "<p>Real body.</p>"
    )
    blocks = wiki_html.content_blocks(html)
    joined = " ".join(b["text"] for b in blocks)
    assert "NESTED_CHROME" not in joined
    assert "OUTER_CHROME" not in joined
    assert any("Real body." in b["text"] for b in blocks)


def test_content_blocks_excludes_chrome_and_folds_nested() -> None:
    html = (
        '<table class="navbox"><tr><td>CHROME</td></tr></table>'
        "<ul><li>Outer<ul><li>Inner</li></ul></li></ul>"
    )
    blocks = wiki_html.content_blocks(html)
    texts = [b["text"] for b in blocks]
    assert "CHROME" not in " ".join(texts)
    assert texts == ["Outer Inner"]  # nested <li> folded into the outer block


def test_content_blocks_drops_div_navbox_chrome() -> None:
    # #2: a template-rendered <div class="navbox"> of place-names survives table-only chrome
    # dropping and leaks into evidence pools. It must be dropped like a <table> navbox.
    html = (
        '<div class="navbox"><div class="navbox-list">'
        "Chillwind Camp Hearthglen Northridge Lumber Camp Plaguewood Tower"
        "</div></div>"
        '<nav role="navigation"><p>NAV_CHROME</p></nav>'
        '<div class="catlinks">Categories: Western Plaguelands</div>'
        "<p>Real body about the Argent Crusade.</p>"
    )
    blocks = wiki_html.content_blocks(html)
    joined = " ".join(b["text"] for b in blocks)
    assert "Chillwind Camp" not in joined
    assert "NAV_CHROME" not in joined
    assert "Categories" not in joined
    assert any("Argent Crusade" in b["text"] for b in blocks)


def test_content_blocks_keeps_plain_content_divs() -> None:
    # A non-chrome <div> wrapping prose must be retained.
    html = '<div class="content"><p>The keep fell to the Scourge.</p></div>'
    blocks = wiki_html.content_blocks(html)
    assert any("keep fell to the Scourge" in b["text"] for b in blocks)


def test_content_blocks_records_inline_links_per_block() -> None:
    # Slice 12: every block carries its own inline article links in document order,
    # deduped per block; absolute wiki links normalize to site-relative paths and
    # fragments are stripped; non-article links are excluded.
    html = (
        "<p>The <a href='/wiki/Argent_Crusade'>Argent Crusade</a> and the "
        "<a href='https://warcraft.wiki.gg/wiki/Cenarion_Circle#History'>Cenarion Circle</a> "
        "heal the land. The <a href='/wiki/Argent_Crusade'>crusade</a> stays; "
        "<a href='https://example.com/offsite'>offsite</a> and <a href='#frag'>frag</a> "
        "do not count.</p>"
        "<p>No links here.</p>"
    )
    blocks = wiki_html.content_blocks(html)
    assert blocks[0]["links"] == [
        {"anchor_text": "Argent Crusade", "href": "/wiki/Argent_Crusade"},
        {"anchor_text": "Cenarion Circle", "href": "/wiki/Cenarion_Circle"},
    ]
    assert blocks[1]["links"] == []


def test_content_blocks_skips_textless_icon_anchors_and_folds_nested_links() -> None:
    html = (
        "<ul><li><a href='/wiki/File:IconSmall.gif'><img src='x.gif'/></a>"
        "<a href='/wiki/Loken'>Loken</a>"
        "<ul><li><a href='/wiki/Volkhan'>Volkhan</a></li></ul></li></ul>"
    )
    blocks = wiki_html.content_blocks(html)
    # One outer block: nested list folded in, icon-only anchor skipped, nested link kept.
    assert [b["links"] for b in blocks] == [
        [
            {"anchor_text": "Loken", "href": "/wiki/Loken"},
            {"anchor_text": "Volkhan", "href": "/wiki/Volkhan"},
        ]
    ]


def test_wiki_article_href_normalizes_and_rejects() -> None:
    assert wiki_html.wiki_article_href("/wiki/Andorhal#History") == "/wiki/Andorhal"
    assert (
        wiki_html.wiki_article_href("https://warcraft.wiki.gg/wiki/Andorhal") == "/wiki/Andorhal"
    )
    assert wiki_html.wiki_article_href("https://example.com/wiki/Andorhal") == ""
    assert wiki_html.wiki_article_href("#history") == ""
    assert wiki_html.wiki_article_href("/wiki/") == ""
    assert wiki_html.wiki_article_href("") == ""


def test_parse_infobox_extracts_label_value_rows() -> None:
    html = (
        '<table class="infobox darktable">'
        "<tr><th>Type</th><td>Dungeon</td></tr>"
        '<tr><th>Expansion</th><td><a href="/wiki/Cataclysm">Cataclysm</a></td></tr>'
        '<tr><td colspan="2">no header</td></tr>'
        "<tr><th>Location</th></tr>"
        "</table>"
    )
    assert wiki_html.parse_infobox(html) == {"Type": "Dungeon", "Expansion": "Cataclysm"}
    assert wiki_html.parse_infobox("<p>no infobox</p>") == {}


def test_parse_infobox_captures_leading_banner_title() -> None:
    # Slice 12: the leading header-only row is the infobox's subject banner and is
    # stored under the reserved "_title" key; a real "Title" label keeps its own key,
    # and a header-only row after fields is an in-box section header, not the title.
    html = (
        '<table class="infobox">'
        '<tr class="above-header"><th colspan="2">Argent Crusade</th></tr>'
        '<tr><td colspan="2">image row</td></tr>'
        "<tr><th>Title</th><td>Highlord</td></tr>"
        "<tr><th>Affiliation</th><td>Independent</td></tr>"
        "<tr><th>Bosses</th></tr>"
        "</table>"
    )
    assert wiki_html.parse_infobox(html) == {
        "_title": "Argent Crusade",
        "Title": "Highlord",
        "Affiliation": "Independent",
    }


def test_iter_headings_and_list_items() -> None:
    html = "<h2>Alpha</h2><h3>Beta</h3><ul><li>one</li><li>two</li></ul>"
    assert wiki_html.iter_headings(html, levels=(2, 3)) == [
        {"level": 2, "text": "Alpha"},
        {"level": 3, "text": "Beta"},
    ]
    assert wiki_html.list_item_texts(html) == ["one", "two"]


def test_ingest_parser_matches_pinned_cases() -> None:
    """Regression pin for the BS4 ingest parser across representative fragments.

    NOTE (WS-A / decision D-A1): text is now entity-decoded, so snapshot bodies and
    their provenance excerpt_hashes differ from the pre-BS4 regex output. Gold must be
    re-baselined on the next live ingest run.
    """
    for name, case in CASES.items():
        sections, links, structured = _extract_sections_and_links(case["html"])
        body, locator = _extract_main_text(case["html"], max_chars=100000)
        assert sections == case["sections"], name
        assert links == case["links"], name
        assert structured == case["structured"], name
        assert body == case["body"], name
        assert locator == case["locator"], name
