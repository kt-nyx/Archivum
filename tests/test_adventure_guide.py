from __future__ import annotations

from pathlib import Path

from pipeline.discovery.adventure_guide import (
    AdventureGuideProvider,
    instance_keys_from_section,
    parse_index_page_titles,
    parse_instance_section,
)

_HUB_WIKITEXT = """
== Instances covered ==
Dungeons:
* [[Adventure Guide Classic dungeons]]
* [[Adventure Guide Mists of Pandaria dungeons]]
Raids:
* [[Adventure Guide Classic raids]]
Also see the [[Adventure Guide]] overview and [[Adventure Guide (API)|the API]].
"""

# index "12" != number "11": Scholomance is filed under Classic dungeons despite its MoP revamp.
_CLASSIC_SECTIONS = [
    {
        "toclevel": 1,
        "level": "2",
        "line": '<a href="/wiki/Blackfathom_Deeps" title="Blackfathom Deeps">Blackfathom Deeps</a>',
        "number": "1",
        "index": "1",
        "anchor": "Blackfathom_Deeps",
    },
    {
        "toclevel": 1,
        "level": "2",
        "line": '<a href="/wiki/Scholomance" title="Scholomance">Scholomance</a>',
        "number": "11",
        "index": "12",
        "anchor": "Scholomance",
    },
    {
        "toclevel": 2,
        "level": "3",
        "line": "Trash",
        "number": "11.1",
        "index": "13",
        "anchor": "Trash",
    },
]

_SCHOLOMANCE_SECTION = """==[[Scholomance]]==
Scholomance is a dungeon in the Caer Darrow area of the Western Plaguelands. Once a Kirin Tor
stronghold, it is now a school of necromancy run by the Scholomance faculty.

{|style="text-align:left"
|{{BossIcon|Instructor Chillheart}}||[[Instructor Chillheart]]<br/>Course: Necromancy 101<br/>Instructor Chillheart journeyed from Northrend to teach aspiring necromancers discipline, harshly punishing those who disappoint her.
|}
{|style="text-align:left"
|{{BossIcon|Lilian Voss}}||[[Lilian Voss|Lillian Voss]]<br/>Course: Reeducation<br/>The undead Lilian Voss strangled her father, a high priest of the Scarlet Crusade, and then began a rampage that led her into Scholomance.
|}
"""


class _FakeFetcher:
    def __init__(self) -> None:
        self.hub_calls = 0
        self.sections_calls = 0
        self.section_calls = 0

    def page_wikitext(self, title: str) -> str:
        self.hub_calls += 1
        return _HUB_WIKITEXT if title == "Adventure Guide" else ""

    def page_sections(self, title: str) -> list[dict[str, object]]:
        self.sections_calls += 1
        if title == "Adventure Guide Classic dungeons":
            return _CLASSIC_SECTIONS
        return []

    def section_wikitext(self, title: str, section_index: str) -> str:
        self.section_calls += 1
        if title == "Adventure Guide Classic dungeons" and str(section_index) == "12":
            return _SCHOLOMANCE_SECTION
        return ""


def test_parse_index_page_titles_keeps_index_pages_only() -> None:
    titles = parse_index_page_titles(_HUB_WIKITEXT)
    assert titles == [
        "Adventure Guide Classic dungeons",
        "Adventure Guide Mists of Pandaria dungeons",
        "Adventure Guide Classic raids",
    ]
    # The hub self-link and the (API) helper page are not index pages.
    assert "Adventure Guide" not in titles


def test_instance_keys_from_section_uses_href_and_display() -> None:
    keys = instance_keys_from_section(_CLASSIC_SECTIONS[1])
    assert "scholomance" in keys


def test_parse_instance_section_splits_overview_and_boss_entries() -> None:
    instance = parse_instance_section(_SCHOLOMANCE_SECTION, instance_title="Scholomance")
    assert "school of necromancy" in instance.overview
    assert "{{" not in instance.overview and "[[" not in instance.overview
    names = [entry.boss_name for entry in instance.entries]
    assert names == ["Instructor Chillheart", "Lilian Voss"]
    chillheart = instance.entries[0]
    assert "journeyed from Northrend" in chillheart.description
    assert chillheart.course == "Necromancy 101"
    # The encounter Course is captured separately, never folded into the framing description.
    assert "Course" not in chillheart.description
    assert "Necromancy 101" not in chillheart.description


def test_entry_for_matches_display_typo_and_qualifier() -> None:
    instance = parse_instance_section(_SCHOLOMANCE_SECTION, instance_title="Scholomance")
    # BossIcon page name is "Lilian Voss"; the displayed link text is the typo "Lillian Voss".
    entry = instance.entry_for("Lillian Voss (tactics)")
    assert entry is not None
    assert entry.boss_name == "Lilian Voss"
    assert "strangled her father" in entry.description


def test_provider_resolves_instance_and_memoizes() -> None:
    fetcher = _FakeFetcher()
    provider = AdventureGuideProvider(fetcher=fetcher)
    instance = provider.instance_content("Scholomance")
    assert instance is not None
    assert len(instance.entries) == 2
    # Second lookup is served from the in-process cache: no additional section fetch.
    again = provider.instance_content("Scholomance")
    assert again is instance
    assert fetcher.section_calls == 1
    assert fetcher.hub_calls == 1


def test_provider_returns_none_for_unlisted_instance() -> None:
    provider = AdventureGuideProvider(fetcher=_FakeFetcher())
    assert provider.instance_content("Karazhan") is None


def test_provider_disk_cache_survives_new_provider(tmp_path: Path) -> None:
    fetcher = _FakeFetcher()
    provider = AdventureGuideProvider(fetcher=fetcher, cache_dir=tmp_path)
    assert provider.instance_content("Scholomance") is not None

    # A fresh provider over the same cache dir reads from disk and never hits the network.
    cold_fetcher = _FakeFetcher()
    warm = AdventureGuideProvider(fetcher=cold_fetcher, cache_dir=tmp_path)
    instance = warm.instance_content("Scholomance")
    assert instance is not None
    assert len(instance.entries) == 2
    assert cold_fetcher.hub_calls == 0
    assert cold_fetcher.section_calls == 0
