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


def test_content_blocks_excludes_chrome_and_folds_nested() -> None:
    html = (
        '<table class="navbox"><tr><td>CHROME</td></tr></table>'
        "<ul><li>Outer<ul><li>Inner</li></ul></li></ul>"
    )
    blocks = wiki_html.content_blocks(html)
    texts = [b["text"] for b in blocks]
    assert "CHROME" not in " ".join(texts)
    assert texts == ["Outer Inner"]  # nested <li> folded into the outer block


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
