from __future__ import annotations

from pipeline.generate.draft.compendium_voice import COMPENDIUM_VOICE_CORE, zone_system_prompt
from pipeline.generate.draft.prose_lint import MAX_AT_A_GLANCE_WORDS, word_count
from pipeline.generate.draft.prose_selection import (
    classify_key_character_role_llm,
    classify_lore_relevance_llm,
    select_key_characters_from_narrative,
)
from pipeline.generate.draft.prose_synthesis import (
    synthesize_at_a_glance,
    synthesize_currently,
    synthesize_faction_summary,
    synthesize_history_sections,
    synthesize_instance_overview,
    synthesize_key_character_summary,
    synthesize_location_summary,
)


def test_at_a_glance_no_llm_prefers_past_heavy_snippet(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    items = [
        {
            "source_id": "src-present",
            "snippet": (
                "Western Plaguelands is a blighted region where crusaders maintain outposts and continue "
                "to heal the soil while factions clash over strategic ruins across the frontier."
            ),
            "section_role": "lead",
        },
        {
            "source_id": "src-past",
            "snippet": (
                "Once the breadbasket of Lordaeron, the region was consumed by the Scourge and remained "
                "blighted for years before recovery efforts began after the Cataclysm."
            ),
            "section_role": "history",
        },
    ]
    summary, used = synthesize_at_a_glance(items, max_words=45)
    assert used == ["src-past"]
    assert "were" in summary or "was" in summary


def test_at_a_glance_system_prompt_uses_compendium_voice() -> None:
    prompt = zone_system_prompt(
        field_voice="Past tense zone caption.", task_lines="Maximum 45 words."
    )
    assert "Compendium Voice" in prompt
    assert "Use present tense" not in prompt


def test_wiki_first_workers_deterministic_fallback_without_llm(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    items = [
        {
            "source_id": "src-zone",
            "snippet": "Western Plaguelands is a blighted region contested by crusaders and undead forces.",
            "section_role": "maps_subregions",
        }
    ]
    summary, used = synthesize_at_a_glance(items, max_words=40)
    assert summary
    assert used == ["src-zone"]
    assert "Compendium Voice" in COMPENDIUM_VOICE_CORE
    sections, used_history = synthesize_history_sections(items, max_sections=2)
    assert sections
    assert used_history


def test_at_a_glance_default_cap_is_forty_five(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = " ".join(["word"] * 80)
    summary, _ = synthesize_at_a_glance([{"source_id": "src", "snippet": snippet}])
    assert word_count(summary) <= MAX_AT_A_GLANCE_WORDS


def test_history_sections_use_section_role_headings(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    items = [
        {
            "source_id": "src-zone",
            "snippet": "The region was devastated during the invasion and fell under undead control.",
            "section_role": "history_third_war",
        }
    ]
    sections, _ = synthesize_history_sections(items, max_sections=3)
    assert sections[0]["heading"] == "History Third War"


def test_currently_deterministic_respects_max_words(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = " ".join(["conflict"] * 200)
    summary, _ = synthesize_currently([{"source_id": "src", "snippet": snippet}], max_words=30)
    assert word_count(summary) <= 30


def test_workers_return_empty_for_empty_pools(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    assert synthesize_at_a_glance([]) == ("", [])
    assert synthesize_currently([]) == ("", [])
    assert synthesize_history_sections([]) == ([], [])
    assert synthesize_faction_summary(
        [], faction_name="Argent Crusade", zone_name="Example Zone"
    ) == ("", [])
    assert synthesize_location_summary(
        [], location_name="Northwatch Hold", zone_name="Example Zone"
    ) == ("", [])


def test_location_summary_deterministic_respects_max_words(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = (
        "Northwatch Hold is a fortified outpost in Example Zone where alliance patrols coordinate "
        "supply lines, defensive operations, and regional scouting missions across the frontier."
    )
    summary, used = synthesize_location_summary(
        [{"source_id": "src-location", "snippet": snippet}],
        location_name="Northwatch Hold",
        zone_name="Example Zone",
        max_words=50,
    )
    assert summary
    assert used == ["src-location"]
    assert word_count(summary) <= 50


def test_faction_summary_deterministic_respects_max_words(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    # Realistic connected prose (not a degenerate token list, which the navbox guard now
    # rightly skips) that overruns the word cap so the truncation path is exercised.
    snippet = (
        "The Argent Crusade presses its long campaign against the Scourge across the "
        "blighted region, reclaiming the fallen keeps and holding the line so that the "
        "living may one day return to the homes that the undead once stole from them all."
    )
    summary, used = synthesize_faction_summary(
        [{"source_id": "src-faction", "snippet": snippet}],
        faction_name="Argent Crusade",
        zone_name="Example Zone",
        max_words=40,
    )
    assert summary
    assert used == ["src-faction"]
    assert word_count(summary) <= 40


def test_instance_overview_deterministic_meets_word_floor(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = (
        "The Archive Vault was built to safeguard forbidden relics after the great war, "
        "and its halls still echo with rival scholars seeking control over grim secrets."
    )
    summary, used = synthesize_instance_overview(
        [{"source_id": "src-instance", "snippet": snippet}],
        instance_name="Archive Vault",
    )
    assert summary
    assert "Archive Vault" in summary
    assert word_count(summary) >= 170
    assert used == ["src-instance"]


def test_key_character_summary_deterministic_includes_boss_name(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    summary, used = synthesize_key_character_summary(
        [{"source_id": "src-instance", "snippet": "Archivist Maelor guards the forbidden stacks."}],
        boss_name="Archivist Maelor",
        instance_name="Archive Vault",
    )
    assert "Archivist Maelor" in summary
    assert "Archive Vault" in summary
    assert used == ["src-instance"]


def test_select_narrative_characters_no_llm_returns_ranking(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    selected = select_key_characters_from_narrative(
        [{"name": "Yogg-Saron"}, {"name": "Loken"}, {"name": "Thorim"}],
        instance_name="Ulduar",
        max_count=2,
    )
    assert selected == ["Yogg-Saron", "Loken"]


def test_select_narrative_characters_llm_is_constrained_to_inputs(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_selection as workers

    monkeypatch.setattr(
        workers, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})()
    )
    monkeypatch.setattr(
        workers,
        "llm_json_with_retry",
        lambda **kwargs: {"selected": ["Loken", "Made Up Name", "yogg-saron"]},
    )
    selected = select_key_characters_from_narrative(
        [{"name": "Yogg-Saron"}, {"name": "Loken"}, {"name": "Thorim"}],
        instance_name="Ulduar",
        max_count=10,
    )
    assert selected == ["Loken", "Yogg-Saron"]


def test_classify_role_llm_returns_fallback_when_offline(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    role = classify_key_character_role_llm(
        [{"snippet": "Some evidence about the figure."}],
        character_name="Mystery NPC",
        instance_name="Ulduar",
        fallback_role="uncertain",
    )
    assert role == "uncertain"


def test_classify_role_llm_uses_constrained_enum(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_selection as workers

    ready = type("S", (), {"openai_ready": True})()
    monkeypatch.setattr(workers, "load_ai_settings", lambda: ready)
    monkeypatch.setattr(workers, "llm_json_with_retry", lambda **kwargs: {"role": "ally"})
    role = classify_key_character_role_llm(
        [{"snippet": "The figure aids the adventurers."}],
        character_name="Mystery NPC",
        instance_name="Ulduar",
        fallback_role="uncertain",
    )
    assert role == "ally"


def test_classify_role_llm_rejects_out_of_enum_value(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_selection as workers

    ready = type("S", (), {"openai_ready": True})()
    monkeypatch.setattr(workers, "load_ai_settings", lambda: ready)
    monkeypatch.setattr(workers, "llm_json_with_retry", lambda **kwargs: {"role": "villain"})
    role = classify_key_character_role_llm(
        [{"snippet": "Ambiguous evidence."}],
        character_name="Mystery NPC",
        instance_name="Ulduar",
        fallback_role="uncertain",
    )
    assert role == "uncertain"


def test_classify_lore_relevance_llm_offline_returns_unrelated(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    verdict = classify_lore_relevance_llm(
        [{"snippet": "Some general complex lore."}],
        page_title="Auchindoun",
        instance_name="Mana-Tombs",
    )
    assert verdict == "unrelated"


def test_classify_lore_relevance_llm_uses_constrained_enum(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_selection as workers

    ready = type("S", (), {"openai_ready": True})()
    monkeypatch.setattr(workers, "load_ai_settings", lambda: ready)
    monkeypatch.setattr(workers, "llm_json_with_retry", lambda **kwargs: {"relevance": "relevant"})
    verdict = classify_lore_relevance_llm(
        [{"snippet": "This page is specifically about the Mana-Tombs."}],
        page_title="Auchindoun",
        instance_name="Mana-Tombs",
    )
    assert verdict == "relevant"


def test_classify_lore_relevance_llm_rejects_out_of_enum(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_selection as workers

    ready = type("S", (), {"openai_ready": True})()
    monkeypatch.setattr(workers, "load_ai_settings", lambda: ready)
    monkeypatch.setattr(workers, "llm_json_with_retry", lambda **kwargs: {"relevance": "maybe"})
    verdict = classify_lore_relevance_llm(
        [{"snippet": "Ambiguous."}],
        page_title="Auchindoun",
        instance_name="Mana-Tombs",
    )
    assert verdict == "unrelated"


def _capture_system_prompt(monkeypatch):
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    import pipeline.generate.draft.prose_synthesis as workers

    captured: dict[str, str] = {}
    ready = type("S", (), {"openai_ready": True})()
    monkeypatch.setattr(workers, "load_ai_settings", lambda: ready)

    def fake_llm(**kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return {"summary": "Synthesized instance prose for the test.", "used_evidence_ids": ["s1"]}

    monkeypatch.setattr(workers, "llm_json_with_retry", fake_llm)
    return captured


def test_instance_overview_prompt_uses_compendium_voice_and_anti_passthrough(monkeypatch) -> None:
    from pipeline.generate.draft.compendium_voice import NO_META_NO_PASSTHROUGH

    captured = _capture_system_prompt(monkeypatch)
    synthesize_instance_overview(
        [{"snippet": "The vault guards forbidden relics.", "source_id": "s1"}],
        instance_name="Archive Vault",
    )
    assert "Compendium Voice" in captured["system_prompt"]
    assert NO_META_NO_PASSTHROUGH in captured["system_prompt"]


def test_key_character_prompt_uses_compendium_voice_and_anti_passthrough(monkeypatch) -> None:
    from pipeline.generate.draft.compendium_voice import NO_META_NO_PASSTHROUGH

    captured = _capture_system_prompt(monkeypatch)
    synthesize_key_character_summary(
        [{"snippet": "The archivist hoards the vault's secrets.", "source_id": "s1"}],
        boss_name="Archivist Maelor",
        instance_name="Archive Vault",
    )
    assert "Compendium Voice" in captured["system_prompt"]
    assert NO_META_NO_PASSTHROUGH in captured["system_prompt"]


def test_instance_at_a_glance_subject_uses_instance_voice(monkeypatch) -> None:
    from pipeline.generate.draft.compendium_voice import NO_META_NO_PASSTHROUGH

    captured = _capture_system_prompt(monkeypatch)
    synthesize_at_a_glance(
        [{"snippet": "A sanctum beneath the World Tree.", "source_id": "s1"}],
        max_words=45,
        subject="Archive Vault",
    )
    assert "Compendium Voice" in captured["system_prompt"]
    assert NO_META_NO_PASSTHROUGH in captured["system_prompt"]


def test_faction_summary_instance_subject_uses_instance_voice(monkeypatch) -> None:
    from pipeline.generate.draft.compendium_voice import NO_META_NO_PASSTHROUGH

    captured = _capture_system_prompt(monkeypatch)
    synthesize_faction_summary(
        [{"snippet": "The Scarlet Crusade holds the vault.", "source_id": "s1"}],
        faction_name="Scarlet Crusade",
        zone_name="Tirisfal",
        instance_name="Archive Vault",
    )
    assert "Compendium Voice" in captured["system_prompt"]
    assert NO_META_NO_PASSTHROUGH in captured["system_prompt"]
