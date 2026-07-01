from __future__ import annotations

from pipeline.common.wiki_evidence_filters import cap_history_pool
from pipeline.generate.draft.prose_election import (
    fallback_currently,
    history_heading_from_role,
    history_section_cap,
    select_at_a_glance_pool,
    select_currently_pool,
    select_history_pool,
)
from pipeline.generate.draft.prose_lint import lint_at_a_glance, lint_currently, word_count


def _item(
    section_role: str,
    snippet: str,
    *,
    cluster_id: str = "",
    source_id: str = "src-zone",
    block_index: int = 0,
    raw_section_role: str = "",
) -> dict:
    return {
        "section_role": section_role,
        "raw_section_role": raw_section_role or section_role,
        "snippet": snippet,
        "cluster_id": cluster_id,
        "source_id": source_id,
        "block_index": block_index,
    }


def _claim_item(snippet: str, *, temporal_scope: str, source_id: str = "src-zone") -> dict:
    return {
        "snippet": snippet,
        "section_role": "lead",
        "raw_section_role": "lead",
        "source_id": source_id,
        "block_index": 0,
        "temporal_scope": temporal_scope,
        "spoiler_safety": "safe_entry_context",
        "is_claim_view": True,
    }


def test_at_a_glance_prefers_entry_state_claims_over_old_origin() -> None:
    """Slice 8 task 2: with claim views, entry-state identity outranks older origin claims."""
    pool = [
        _claim_item("The order was founded in a distant age.", temporal_scope="pre_entry_history"),
        _claim_item("The order now garrisons the keep and holds the road.", temporal_scope="entry_state"),
    ]

    selected = select_at_a_glance_pool(pool)

    assert selected[0]["snippet"] == "The order now garrisons the keep and holds the road."


def test_currently_prefers_entry_state_claims() -> None:
    """Slice 8 task 1: the current pool anchors on entry-state before older background."""
    pool = {
        "currently_pool": [
            _claim_item("The order keeps a long lineage of scholars.", temporal_scope="pre_entry_history"),
            _claim_item("The valley is contested by rival forces.", temporal_scope="entry_state"),
        ]
    }

    selected = select_currently_pool(pool)

    assert selected[0]["snippet"] == "The valley is contested by rival forces."
    # Both safe claims survive; the reorder (not exclusion) is what promotes the entry-state one.
    assert len(selected) == 2


def test_currently_promotes_present_state_lore_over_quest_directive() -> None:
    # A zone whose quest evidence is a player-facing directive ("Adventurers are tasked...") but
    # whose lore carries genuine present-state framing must surface the lore, not the directive.
    pool = {
        "currently_pool": [
            _item(
                "quests_or_storyline",
                "Adventurers are tasked with aiding their faction in the battle for the keep.",
            ),
            _item(
                "history",
                "The Argent Crusade still holds the reclaimed valley while rival forces contest "
                "its borders.",
            ),
        ]
    }
    selected = select_currently_pool(pool, zone_name="Example Zone")
    assert selected
    assert "Argent Crusade still holds" in selected[0]["snippet"]
    assert all("Adventurers are tasked" not in item["snippet"] for item in selected)


def test_fallback_currently_skips_player_directive_for_present_state_lore() -> None:
    # The directive snippet is the longest; blind-longest selection would borrow it. The hardened
    # fallback drops directives and prefers present-state lore framing instead.
    items = [
        _item(
            "quests_or_storyline",
            "Adventurers are tasked with aiding their faction in the long and grinding battle for "
            "the ruined keep that dominates the contested frontier of the blighted region.",
        ),
        _item("history", "The Argent Crusade still holds the reclaimed valley."),
    ]
    text, _ = fallback_currently(items)
    assert "Argent Crusade still holds" in text
    assert "Adventurers are tasked" not in text


def test_lint_currently_flags_player_directive() -> None:
    issues = lint_currently(
        "Adventurers are tasked with aiding their faction in the battle for the keep.",
        zone_name="Example Zone",
    )
    assert any("player-facing quest directive" in issue for issue in issues)


def test_history_heading_prefers_distinct_subsection_text() -> None:
    """#8: distinct history subsections get distinct headings, not a single constant.

    Both blocks classify to the generic "history"/"other" role, but their raw subsection
    headings differ, so the heading must be derived from the subsection text.
    """
    a = history_heading_from_role("history", "the_scourging_edit")
    b = history_heading_from_role("history", "cataclysm_edit")
    assert a == "The Scourging"
    assert b == "Cataclysm"
    assert a != b


def test_history_heading_falls_back_to_constant_when_no_subsection() -> None:
    # No raw subsection and a generic/empty role -> the documented constant.
    assert history_heading_from_role("other", "") == "Historical era"
    assert history_heading_from_role("other", "history_edit") == "Historical era"
    # A recognized canonical role with no distinct subsection -> role label.
    assert history_heading_from_role("wrath_of_the_lich_king_edit", "") == "Wrath Of The Lich King"


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
    items = [_item("history", " ".join(["Event"] * 110)) for _ in range(8)]
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


def test_select_history_pool_orders_by_block_index() -> None:
    items = [
        _item(
            "cataclysm_edit",
            " ".join(["Cataclysm"] * 30),
            block_index=3,
            raw_section_role="cataclysm_edit",
        ),
        _item("history", " ".join(["Early"] * 30), block_index=1, raw_section_role="history_edit"),
        _item("history", " ".join(["Middle"] * 30), block_index=2, raw_section_role="history_edit"),
    ]
    selected = select_history_pool(items)
    assert [row["block_index"] for row in selected] == [1, 2, 3]


def test_cap_history_pool_keeps_trailing_named_sections() -> None:
    items = [
        _item(
            "history", " ".join(["Early"] * 30), block_index=index, raw_section_role="history_edit"
        )
        for index in range(1, 6)
    ]
    items.extend(
        [
            _item(
                "cataclysm_edit",
                " ".join(["Cataclysm"] * 30),
                block_index=6,
                raw_section_role="cataclysm_edit",
            ),
            _item(
                "battle_for_azeroth",
                " ".join(["BFA"] * 30),
                block_index=7,
                raw_section_role="battle_for_azeroth",
            ),
        ]
    )
    pool = select_history_pool(items)
    capped = cap_history_pool(pool, cap=5)
    assert len(capped) == 5
    assert capped[-1]["raw_section_role"] == "battle_for_azeroth"


def test_fallback_at_a_glance_prefers_present_state_snippet() -> None:
    # at_a_glance is a present-tense identity caption, so the fallback now prefers a present-state
    # snippet ("the region is a ...") over a purely past historical one.
    from pipeline.generate.draft.prose_election import fallback_at_a_glance

    items = [
        {
            "source_id": "src-past",
            "snippet": "The region was devastated during the invasion and fell under undead control for decades.",
            "section_role": "history",
        },
        {
            "source_id": "src-present",
            "snippet": "The region is a reclaimed but blighted frontier that the Argent Crusade still holds.",
            "section_role": "lead",
        },
    ]
    summary, used = fallback_at_a_glance(items)
    assert used == ["src-present"]
    assert "is" in summary or "holds" in summary


def test_lint_helpers_flag_word_cap_and_meta() -> None:
    glance = " ".join(["word"] * 50)
    assert lint_at_a_glance(glance)
    currently = "Players can earn reputation with the faction while exploring Eastern Plaguelands."
    assert lint_currently(currently)
    assert word_count("one two three") == 3
