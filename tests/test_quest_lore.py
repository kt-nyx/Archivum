from __future__ import annotations

from pipeline.discovery.quest_lore import build_quest_lore_record, extract_quest_lore, lore_word_count


def test_extract_quest_lore_includes_description_and_objectives() -> None:
    blocks = [
        {"section_role": "description", "text": "The crusaders need help reclaiming the ruined district from undead forces."},
        {"section_role": "objectives", "text": "Speak with the quartermaster and recover the sealed orders from the crypt."},
        {"section_role": "rewards", "text": "You will receive: 15 silver, 250 reputation, Item Link x1."},
    ]
    snippets = extract_quest_lore(blocks)
    roles = {row["section_role"] for row in snippets}
    assert "description" in roles
    assert "objectives" in roles
    assert "rewards" not in roles
    assert lore_word_count(snippets) >= 10


def test_extract_quest_lore_skips_boilerplate_tables() -> None:
    blocks = [
        {
            "section_role": "rewards",
            "text": "wowhead db link | Item | Quantity | Patch 4.0.1 | level 15 quest",
        }
    ]
    assert extract_quest_lore(blocks) == []


def test_extract_quest_lore_does_not_fallback_to_non_narrative_sections() -> None:
    blocks = [
        {
            "section_role": "notes",
            "text": "This notes section has enough words to pass the minimum snippet length gate.",
        }
    ]
    assert extract_quest_lore(blocks) == []


def test_build_quest_lore_record_shape() -> None:
    blocks = [
        {"section_role": "lead", "text": "A messenger arrives with urgent news about the front lines."},
    ]
    record = build_quest_lore_record(
        zone_id="zone-example",
        cluster_id="cluster-alpha",
        node_id="quest-alpha",
        quest_title="Quest Alpha",
        source_link="/wiki/Quest_Alpha",
        section_blocks=blocks,
    )
    assert record["cluster_id"] == "cluster-alpha"
    assert record["lore_word_count"] >= 5
    assert record["snippets"]
