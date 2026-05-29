from __future__ import annotations

import os

from pipeline.generate.draft.prose_lint import MAX_AT_A_GLANCE_WORDS, word_count
from pipeline.generate.draft.wiki_first_workers import (
    synthesize_at_a_glance,
    synthesize_currently,
    synthesize_faction_summary,
    synthesize_history_sections,
)


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
    assert synthesize_faction_summary([], faction_name="Argent Crusade", zone_name="Example Zone") == ("", [])


def test_faction_summary_deterministic_respects_max_words(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = " ".join(["reclamation"] * 200) + "."
    summary, used = synthesize_faction_summary(
        [{"source_id": "src-faction", "snippet": snippet}],
        faction_name="Argent Crusade",
        zone_name="Example Zone",
        max_words=40,
    )
    assert summary
    assert used == ["src-faction"]
    assert word_count(summary) <= 40

