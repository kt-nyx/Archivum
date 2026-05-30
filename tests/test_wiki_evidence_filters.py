from __future__ import annotations

from pipeline.common.wiki_evidence_filters import (
    cap_history_pool,
    is_expansion_boilerplate,
    is_named_history_section,
    is_non_canon_history_snippet,
    is_rpg_section,
    is_simile_continent_mention,
    should_exclude_from_history,
    trailing_named_section_items,
)
from pipeline.discovery.enrich import _is_geography_input_role


def test_is_rpg_section_prefix() -> None:
    assert is_rpg_section("in_the_rpg")
    assert is_rpg_section("in_the_rpg_history_edit")
    assert not is_rpg_section("history_edit")


def test_is_non_canon_history_snippet_markers() -> None:
    assert is_non_canon_history_snippet("This material is non-canon according to Blizzard.")
    assert is_non_canon_history_snippet("From the Warcraft RPG sourcebook.")
    assert not is_non_canon_history_snippet("The Scourge invaded during the Third War.")


def test_is_expansion_boilerplate() -> None:
    assert is_expansion_boilerplate("This section concerns content related to the War Within.")
    assert not is_expansion_boilerplate("Recovery efforts continued across the zone.")


def test_is_geography_input_role_rejects_rpg_prefix() -> None:
    assert not _is_geography_input_role("in_the_rpg_geography_edit")
    assert _is_geography_input_role("geography_edit")


def test_should_exclude_from_history_rpg_section() -> None:
    assert should_exclude_from_history(
        {
            "snippet": "A long historical paragraph about the kingdom before the plague arrived.",
            "raw_section_role": "in_the_rpg_history",
        }
    )


def test_is_named_history_section() -> None:
    assert is_named_history_section("cataclysm_edit")
    assert is_named_history_section("battle_for_azeroth")
    assert not is_named_history_section("history_edit")
    assert not is_named_history_section("geography_edit")
    assert not is_named_history_section("in_the_rpg_history")


def test_is_simile_continent_mention() -> None:
    assert is_simile_continent_mention("Just as in Northrend, the cold preserved the dead.", "Northrend")
    assert not is_simile_continent_mention("Western Plaguelands lies in northern Lordaeron.", "Northrend")


def test_trailing_named_section_items() -> None:
    items = [
        {"raw_section_role": "history_edit", "block_index": 1, "source_id": "src", "snippet": "early"},
        {"raw_section_role": "cataclysm_edit", "block_index": 2, "source_id": "src", "snippet": "cata"},
        {"raw_section_role": "battle_for_azeroth", "block_index": 3, "source_id": "src", "snippet": "bfa"},
    ]
    trailing = trailing_named_section_items(items, max_groups=2)
    assert len(trailing) == 2
    assert trailing[0]["snippet"] == "cata"
    assert trailing[1]["snippet"] == "bfa"


def test_cap_history_pool_preserves_trailing_sections() -> None:
    items = [
        {
            "raw_section_role": "history_edit",
            "section_role": "history",
            "block_index": index,
            "source_id": "src",
            "snippet": " ".join(["Event"] * 30),
        }
        for index in range(1, 6)
    ]
    items.extend(
        [
            {
                "raw_section_role": "cataclysm_edit",
                "section_role": "cataclysm_edit",
                "block_index": 6,
                "source_id": "src",
                "snippet": " ".join(["Cataclysm"] * 30),
            },
            {
                "raw_section_role": "cataclysm_edit",
                "section_role": "cataclysm_edit",
                "block_index": 7,
                "source_id": "src",
                "snippet": " ".join(["CataclysmMore"] * 30),
            },
            {
                "raw_section_role": "battle_for_azeroth",
                "section_role": "battle_for_azeroth",
                "block_index": 8,
                "source_id": "src",
                "snippet": " ".join(["BFA"] * 30),
            },
        ]
    )
    capped = cap_history_pool(items, cap=5)
    assert len(capped) == 5
    assert any(item["raw_section_role"] == "battle_for_azeroth" for item in capped)
    assert sum(1 for item in capped if item["raw_section_role"] == "cataclysm_edit") == 2
