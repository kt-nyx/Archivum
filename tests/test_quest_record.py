from __future__ import annotations

from pathlib import Path

from pipeline.contracts.models import QuestRecord
from pipeline.discovery.quest_record import (
    build_quest_record,
    faction_disambiguation_variants,
    parse_parsetree,
)

FIXTURE_DIR = Path("tests/fixtures/quest")


def _load(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_parses_questbox_fields_with_coords_and_chain() -> None:
    record = build_quest_record(
        zone_id="zone-nagrand",
        node_id="quest-a-head-full-of-ivory",
        quest_title="A Head Full of Ivory",
        source_link="/wiki/A_Head_Full_of_Ivory",
        parse_tree=_load("a_head_full_of_ivory.parsetree.xml"),
        section_blocks=[
            {"section_role": "description", "text": "Gather the kurenai relics scattered across Nagrand."}
        ],
    )
    assert record is not None
    assert record["has_questbox"] is True
    assert record["start_npc"] == "Nasota Sandhoof"
    assert record["start_coords"] == "47.2, 34.8"
    assert record["start_location"] == "Nagrand"
    assert record["end_npc"] == "Nasota Sandhoof"
    assert record["category"] == "Nagrand"
    assert record["reputation_org"] == "Kurenai"
    assert record["previous"] == ["Murkblood Investigation"]
    assert record["next"] == ["More Heads Full of Ivory"]
    assert record["faction"] == "shared"
    assert record["description"]
    # Round-trips through the pydantic contract.
    QuestRecord.model_validate(record)


def test_parses_shadowlands_quest() -> None:
    record = build_quest_record(
        zone_id="zone-bastion",
        node_id="quest-seek-the-ascended",
        quest_title="Seek the Ascended",
        source_link="/wiki/Seek_the_Ascended",
        parse_tree=_load("seek_the_ascended.parsetree.xml"),
    )
    assert record is not None
    assert record["start_npc"] == "Kleia"
    assert record["start_coords"] == "34.9, 56.1"
    assert record["start_location"] == "Bastion"
    assert record["next"] == ["The Path to Ascension"]
    assert record["previous"] == []
    QuestRecord.model_validate(record)


def test_infers_faction_from_side() -> None:
    record = build_quest_record(
        zone_id="zone-western-plaguelands",
        node_id="quest-the-battle-for-andorhal",
        quest_title="The Battle for Andorhal",
        source_link="/wiki/The_Battle_for_Andorhal_(Alliance)",
        parse_tree=_load("battle_for_andorhal_alliance.parsetree.xml"),
    )
    assert record is not None
    assert record["faction"] == "alliance"
    assert record["start_npc"] == "Thassarian"
    assert record["category"] == "Western Plaguelands"
    QuestRecord.model_validate(record)


def test_faction_disambiguation_returns_variants() -> None:
    parse_tree = _load("combat_training_faction_disambig.parsetree.xml")
    record = build_quest_record(
        zone_id="zone-azuremyst-isle",
        node_id="quest-combat-training",
        quest_title="Combat Training",
        source_link="/wiki/Combat_Training",
        parse_tree=parse_tree,
    )
    assert record is not None
    assert record["has_questbox"] is False
    assert record["faction_mirror"] == ["Combat Training (Alliance)", "Combat Training (Horde)"]

    root = parse_parsetree(parse_tree)
    assert root is not None
    assert faction_disambiguation_variants(root) == [
        "Combat Training (Alliance)",
        "Combat Training (Horde)",
    ]


def test_non_quest_page_returns_none() -> None:
    not_a_quest = "<root>Just some prose with a [[link]] and no infobox template.</root>"
    assert (
        build_quest_record(
            zone_id="zone-x",
            node_id="quest-x",
            quest_title="X",
            source_link="/wiki/X",
            parse_tree=not_a_quest,
        )
        is None
    )


def test_empty_parse_tree_returns_none() -> None:
    assert (
        build_quest_record(
            zone_id="zone-x",
            node_id="quest-x",
            quest_title="X",
            source_link="/wiki/X",
            parse_tree="",
        )
        is None
    )
