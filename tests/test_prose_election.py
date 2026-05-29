from __future__ import annotations

from pipeline.generate.draft.prose_election import (
    history_section_cap,
    select_at_a_glance_pool,
    select_currently_pool,
    select_history_pool,
)
from pipeline.generate.draft.prose_lint import lint_at_a_glance, lint_currently, word_count


def _item(section_role: str, snippet: str, *, cluster_id: str = "", source_id: str = "src-zone") -> dict:
    return {
        "section_role": section_role,
        "snippet": snippet,
        "cluster_id": cluster_id,
        "source_id": source_id,
    }


def test_select_at_a_glance_pool_orders_history_before_geography() -> None:
    items = [
        _item("maps_subregions", "Andorhal, Hearthglen, and Stratholme dominate the region."),
        _item("history", "The zone fell during the Third War and remained blighted for decades."),
        _item("lead", "A contested frontier between crusaders and undead remnants."),
    ]
    selected = select_at_a_glance_pool(items)
    assert selected[0]["section_role"] == "lead"
    assert any(row["section_role"] == "history" for row in selected)


def test_select_currently_pool_prefers_expansion_edit_tier() -> None:
    pools = {
        "currently_pool": [
            _item("quests_edit", "Current quest activity continues around the capital district."),
            _item(
                "cataclysm_edit",
                "Recovery efforts after the Cataclysm still reshape roads and outposts across the zone.",
            ),
        ],
        "history_pool": [],
        "quest_cluster_lore_pool": [],
    }
    selected = select_currently_pool(pools, zone_name="Example Zone")
    assert selected
    assert selected[0]["section_role"] == "cataclysm_edit"


def test_select_currently_pool_uses_cluster_lore_when_higher_tiers_empty() -> None:
    pools = {
        "currently_pool": [
            _item(
                "quests",
                "Formerly the grain heartland of the kingdom before the plague arrived years ago.",
            ),
        ],
        "history_pool": [],
        "quest_cluster_lore_pool": [
            _item(
                "description",
                "Crusaders and druids continue to push back undead forces along the main road.",
                cluster_id="part-1",
            )
        ],
    }
    selected = select_currently_pool(pools, zone_name="Example Zone")
    assert len(selected) == 1
    assert selected[0]["cluster_id"] == "part-1"


def test_select_history_pool_excludes_geography_roles() -> None:
    items = [
        _item("geography_edit", "Geography details that should not become history sections."),
        _item(
            "history",
            (
                "The region suffered catastrophic collapse before long-term military campaigns "
                "began restoring order across the ruined frontier, broken keeps, and scattered "
                "villages that once formed the kingdom agricultural heartland."
            ),
        ),
    ]
    selected = select_history_pool(items)
    assert len(selected) == 1
    assert selected[0]["section_role"] == "history"


def test_history_section_cap_bumps_to_eight_for_large_pools() -> None:
    items = [
        _item("history", " ".join(["Event"] * 110))
        for _ in range(8)
    ]
    assert history_section_cap(items) == 8


def test_select_currently_pool_tier4_requires_expansion_signal() -> None:
    pools = {
        "currently_pool": [
            _item("quests", "Formerly blighted farmland before the plague arrived years ago."),
        ],
        "history_pool": [
            _item(
                "cataclysm_edit",
                "Recovery efforts after the Cataclysm reshaped roads while undead remnants were pushed back.",
            )
        ],
        "quest_cluster_lore_pool": [],
    }
    assert select_currently_pool(pools, zone_name="Example Zone") == []


def test_select_currently_pool_tier4_uses_history_when_expansion_signal_present() -> None:
    pools = {
        "currently_pool": [
            _item(
                "cataclysm_edit",
                "Formerly blighted farmland before recovery efforts began years ago.",
            ),
        ],
        "history_pool": [
            _item(
                "cataclysm_edit",
                (
                    "Recovery efforts after the Cataclysm reshaped roads and outposts while "
                    "undead remnants were pushed back across the frontier."
                ),
            )
        ],
        "quest_cluster_lore_pool": [],
    }
    selected = select_currently_pool(pools, zone_name="Example Zone")
    assert len(selected) == 1
    assert selected[0]["section_role"] == "cataclysm_edit"
    assert "Recovery efforts" in selected[0]["snippet"]


def test_lint_helpers_flag_word_cap_and_meta() -> None:
    glance = " ".join(["word"] * 50)
    assert lint_at_a_glance(glance)
    currently = "Players can earn reputation with the faction while exploring Eastern Plaguelands."
    assert lint_currently(currently)
    assert word_count("one two three") == 3
