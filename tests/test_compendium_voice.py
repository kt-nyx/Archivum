from __future__ import annotations

from pipeline.generate.draft.compendium_voice import (
    AT_A_GLANCE_VOICE,
    COMPENDIUM_VOICE_CORE,
    CURRENTLY_VOICE,
    HISTORY_VOICE,
    INSTANCE_OVERVIEW_VOICE,
    zone_system_prompt,
)


def test_compendium_voice_core_is_present_in_constants() -> None:
    assert "Compendium Voice" in COMPENDIUM_VOICE_CORE
    assert "in-universe" in COMPENDIUM_VOICE_CORE.lower()


def test_zone_system_prompt_composes_core_and_field_voice() -> None:
    prompt = zone_system_prompt(field_voice=AT_A_GLANCE_VOICE, task_lines="Maximum 45 words.")
    assert COMPENDIUM_VOICE_CORE.split(".")[0] in prompt
    # at_a_glance is now an atmospheric essence caption (history via adjectives, no past narration).
    assert "essence caption" in prompt
    assert "Maximum 45 words." in prompt


def test_field_voice_constants_cover_zone_core_fields() -> None:
    assert "essence caption" in AT_A_GLANCE_VOICE
    assert "Present tense only" in CURRENTLY_VOICE
    assert "Encyclopedic reference voice" in HISTORY_VOICE


def test_voice_fragments_carry_slice_c_guidance() -> None:
    # at_a_glance is an atmospheric essence caption: carry history through adjectives, never narrate
    # it with finite past-tense verbs.
    assert "essence caption" in AT_A_GLANCE_VOICE.lower()
    assert "do not narrate the past" in AT_A_GLANCE_VOICE.lower()
    # at_a_glance is almost pure atmosphere: it must not name factions/characters or who holds the
    # zone (that is the Argent-Crusade-holds-Hearthglen tag-on we want gone) — that is 'currently'.
    voice = AT_A_GLANCE_VOICE.lower()
    assert "atmosphere" in voice
    assert "do not name" in voice
    # history stays past with simple-past discipline (no gratuitous "had been").
    assert "simple past" in HISTORY_VOICE.lower()
    # currently describes the whole zone's present state, not a single questline.
    assert "overall present state" in CURRENTLY_VOICE.lower()
    assert "single battle or questline" in CURRENTLY_VOICE.lower()
    # instance overview stays high-level and defers granular events to history.
    assert "high-level" in INSTANCE_OVERVIEW_VOICE.lower()
    assert "history sections" in INSTANCE_OVERVIEW_VOICE.lower()
