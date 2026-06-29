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
    assert "Past tense only" in prompt
    assert "Maximum 45 words." in prompt
    assert "Use present tense" not in prompt


def test_field_voice_constants_cover_zone_core_fields() -> None:
    assert "Past tense only" in AT_A_GLANCE_VOICE
    assert "Present tense only" in CURRENTLY_VOICE
    assert "Reference-chronicle blend" in HISTORY_VOICE


def test_voice_fragments_carry_slice_c_guidance() -> None:
    # Simple-past discipline (no gratuitous "had been") on both past-tense fields.
    assert "simple past" in AT_A_GLANCE_VOICE.lower()
    assert "past-perfect" in AT_A_GLANCE_VOICE.lower()
    assert "simple past" in HISTORY_VOICE.lower()
    # currently describes the whole zone's present state, not a single questline.
    assert "overall present state" in CURRENTLY_VOICE.lower()
    assert "single battle or questline" in CURRENTLY_VOICE.lower()
    # instance overview stays high-level and defers granular events to history.
    assert "high-level" in INSTANCE_OVERVIEW_VOICE.lower()
    assert "history sections" in INSTANCE_OVERVIEW_VOICE.lower()
