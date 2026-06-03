from __future__ import annotations

import os

import pytest

from pipeline.generate.draft.card_lint import lint_cta_hook
from pipeline.generate.draft.wiki_first_workers import (
    filter_early_chain_evidence_pool,
    synthesize_questline_cta_hook,
)


def test_filter_early_chain_evidence_pool_limits_to_chain_heads() -> None:
    items = [
        {"quest_node_id": "quest-a", "snippet": "Early beat.", "source_id": "src-a"},
        {"quest_node_id": "quest-b", "snippet": "Mid beat.", "source_id": "src-b"},
        {"quest_node_id": "quest-c", "snippet": "Late beat.", "source_id": "src-c"},
    ]
    scoped = filter_early_chain_evidence_pool(
        items,
        ["quest-a", "quest-b", "quest-c", "quest-d"],
        arc_title="Andorhal Campaign",
    )
    assert {row["quest_node_id"] for row in scoped}.issubset({"quest-a", "quest-b", "quest-c", "quest-d"})
    assert len(scoped) <= 6


@pytest.mark.parametrize("no_llm", ["1"])
def test_synthesize_questline_cta_hook_no_llm_passes_lint(monkeypatch, no_llm: str) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", no_llm)
    items = [
        {
            "quest_node_id": "quest-hero-s-call-western-plaguelands",
            "snippet": "Push back the Scourge and secure the ruined city before the Forsaken advance.",
            "source_id": "src-hero",
        },
        {
            "quest_node_id": "quest-late",
            "snippet": "Finale spoilers about who wins the city.",
            "source_id": "src-late",
        },
    ]
    hook, used = synthesize_questline_cta_hook(
        items,
        arc_title="Andorhal Campaign (Alliance)",
        start_anchor="Hero's Call: Western Plaguelands!",
        faction="alliance",
        chain_refs=["quest-hero-s-call-western-plaguelands", "quest-late"],
        quest_descriptions={
            "quest-hero-s-call-western-plaguelands": (
                "Push back the Scourge and secure the ruined city before the Forsaken advance."
            )
        },
        max_words=35,
    )
    assert used
    assert hook
    assert hook.lower() != "andorhal campaign (alliance)"
    assert not lint_cta_hook(hook)
    assert "Western Plaguelands" not in hook
