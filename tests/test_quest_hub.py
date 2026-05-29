from __future__ import annotations

from pathlib import Path

from pipeline.discovery.quest_hub import is_quest_hub_page, resolve_hub_child_links

FIXTURE = Path("tests/fixtures/storyline/quest_hub_page.html")


def test_quest_hub_page_detected_from_html_fixture() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    assert is_quest_hub_page([], parse_html=html, zone_name="Example Zone")


def test_resolve_hub_child_links_returns_valid_quest_urls() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    children = resolve_hub_child_links([], parse_html=html, zone_name="Example Zone")
    assert children == ["/wiki/Quest_Alpha", "/wiki/Quest_Beta"]


def test_hub_detected_from_wiki_links_without_parse_html() -> None:
    wiki_links = ["/wiki/Quest_Alpha", "/wiki/Quest_Beta"]
    blocks = [{"section_role": "other", "text": "This quest chain branches into two paths."}]
    assert is_quest_hub_page(blocks, wiki_links=wiki_links, zone_name="Example Zone")
    children = resolve_hub_child_links(blocks, wiki_links=wiki_links, zone_name="Example Zone")
    assert children == ["/wiki/Quest_Alpha", "/wiki/Quest_Beta"]


def test_non_hub_page_with_rich_lore_is_not_hub() -> None:
    blocks = [
        {
            "section_role": "description",
            "text": " ".join(["Narrative detail"] * 30),
        }
    ]
    assert not is_quest_hub_page(blocks, zone_name="Example Zone")
