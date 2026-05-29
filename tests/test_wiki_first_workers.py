from __future__ import annotations

import os

from pipeline.generate.draft.wiki_first_workers import (
    synthesize_at_a_glance,
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
