from __future__ import annotations

from pipeline.common.wiki_category_registry import (
    classify_category,
    classify_page_categories,
)


def test_strong_include_parent_beats_soft_drop_parent() -> None:
    signal = classify_category("Factions", ["Organizations", "Reputation"])

    assert signal.bucket == "faction"
    assert signal.disposition == "strong_include"
    assert "Organizations" in signal.matched_roots


def test_strong_drop_parent_beats_lore_token() -> None:
    signal = classify_category("Speculation", ["Lore", "User created content"])

    assert signal.bucket == "noise"
    assert signal.disposition == "strong_drop"
    assert "User created content" in signal.matched_roots


def test_lore_alone_is_not_a_strong_include() -> None:
    signal = classify_category("Lore", [])

    assert signal.bucket == "concept"
    assert signal.disposition == "review"


def test_event_roots_are_strong_includes() -> None:
    signal = classify_category("Wars", ["Events", "Lore"])

    assert signal.bucket == "event"
    assert signal.disposition == "strong_include"


def test_page_categories_drop_generic_race_and_school_pages() -> None:
    human = classify_page_categories(["Races"], {"Races": ["World of Warcraft"]})
    academy = classify_page_categories(
        ["Disambiguations", "Schools"],
        {"Schools": ["World of Warcraft"], "Disambiguations": ["Hidden categories"]},
    )

    assert human.bucket == "noise"
    assert human.disposition == "soft_drop"
    assert academy.bucket == "noise"
    assert academy.disposition == "strong_drop"


def test_page_categories_drop_generic_creatures_but_keep_lore_events() -> None:
    lich = classify_page_categories(["Liches"], {"Liches": ["World of Warcraft creatures"]})
    third_war = classify_page_categories(["Wars"], {"Wars": ["Events", "Lore"]})

    assert lich.bucket == "noise"
    assert lich.disposition == "soft_drop"
    assert third_war.bucket == "event"
    assert third_war.disposition == "strong_include"


def test_page_strong_include_beats_maintenance_and_speculation_categories() -> None:
    lich_king = classify_page_categories(
        [
            "Arthas: Rise of the Lich King characters",
            "Pages using deprecated location templates",
            "Speculation",
        ],
        {
            "Arthas: Rise of the Lich King characters": ["Characters by appearances"],
            "Pages using deprecated location templates": ["Hidden categories"],
            "Speculation": ["Lore", "User created content"],
        },
    )
    plague = classify_page_categories(
        ["Afflictions", "Speculation"],
        {
            "Afflictions": ["Magic"],
            "Speculation": ["Lore", "User created content"],
        },
    )

    assert lich_king.bucket == "person"
    assert lich_king.disposition == "strong_include"
    assert plague.bucket == "event"
    assert plague.disposition == "strong_include"


def test_direct_fatal_drop_categories_beat_strong_includes() -> None:
    disambiguated_faction = classify_page_categories(
        ["Disambiguations", "Factions"],
        {
            "Disambiguations": ["Warcraft Wiki"],
            "Factions": ["Organizations", "Reputation"],
        },
    )
    image_character = classify_page_categories(
        ["Images", "Characters"],
        {
            "Images": ["Media"],
            "Characters": ["Lore"],
        },
    )

    assert disambiguated_faction.bucket == "noise"
    assert disambiguated_faction.disposition == "strong_drop"
    assert "Disambiguations" in disambiguated_faction.matched_roots
    assert image_character.bucket == "noise"
    assert image_character.disposition == "strong_drop"
    assert "Images" in image_character.matched_roots


def test_generic_npc_occupation_page_does_not_become_a_person() -> None:
    necromancer = classify_page_categories(
        ["NPC occupations", "World of Warcraft: The Roleplaying Game"],
        {
            "NPC occupations": ["Culture", "Lore", "NPCs"],
            "World of Warcraft: The Roleplaying Game": ["Warcraft RPG"],
        },
    )

    assert necromancer.bucket == "noise"
    assert necromancer.disposition in {"soft_drop", "strong_drop"}


def test_event_categories_beat_contextual_place_and_faction_categories() -> None:
    signal = classify_page_categories(
        ["Battles", "Wars", "Dalaran", "Alliance"],
        {
            "Battles": ["Events"],
            "Wars": ["Events", "Lore"],
            "Dalaran": ["Cities"],
            "Alliance": ["Organizations"],
        },
    )

    assert signal.bucket == "event"
    assert signal.disposition == "strong_include"
