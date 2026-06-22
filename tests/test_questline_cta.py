from __future__ import annotations

import pytest

from pipeline.generate.draft.card_lint import (
    finalize_cta_hook,
    lint_cta_hook,
    strip_zone_name_from_cta,
)
from pipeline.generate.draft.prose_gate import detect_midsentence_gap
from pipeline.generate.draft.prose_synthesis import (
    filter_early_chain_evidence_pool,
    synthesize_questline_cta_hook,
)


@pytest.mark.parametrize(
    ("hook", "expected"),
    [
        # The two real Andorhal defects (#3): zone name as the object of a preposition /
        # article. A raw substring strip left "Answer the call to, where" and "contest the
        # and every road"; the grammar-safe strip drops the governing function word with it.
        (
            "Answer the call to Western Plaguelands, where the Scourge still festers.",
            "Answer the call, where the Scourge still festers.",
        ),
        (
            "Hold the line and contest the Western Plaguelands and every road and farmstead.",
            "Hold the line and contest every road and farmstead.",
        ),
        # Preposition governs the zone but a conjunction joins two verbs -> keep the conj.
        (
            "March to Western Plaguelands and reclaim the fallen city.",
            "March and reclaim the fallen city.",
        ),
        # Preposition + article governing the zone are both consumed.
        (
            "Fight in the Western Plaguelands to save the living.",
            "Fight to save the living.",
        ),
        # Bare leading mention -> capitalize the new sentence head.
        (
            "Western Plaguelands beckons every champion to the front.",
            "Beckons every champion to the front.",
        ),
        # No zone mention -> untouched.
        (
            "Push back the Scourge and secure the ruined city.",
            "Push back the Scourge and secure the ruined city.",
        ),
    ],
)
def test_strip_zone_name_from_cta_is_grammar_safe(hook: str, expected: str) -> None:
    out = strip_zone_name_from_cta(hook, zone_name="Western Plaguelands")
    assert out == expected
    assert not detect_midsentence_gap(out)
    assert not lint_cta_hook(finalize_cta_hook(out))


def test_strip_zone_name_from_cta_no_op_without_zone() -> None:
    hook = "Answer the call to, where the Scourge still festers."
    assert strip_zone_name_from_cta(hook, zone_name="") == hook
    assert strip_zone_name_from_cta(hook, zone_name="   ") == hook


def test_strip_zone_name_keeps_original_when_strip_empties_it() -> None:
    # Stripping every word (zone == whole clause) must not yield an empty hook.
    assert (
        strip_zone_name_from_cta("Western Plaguelands.", zone_name="Western Plaguelands")
        == "Western Plaguelands."
    )


def test_lint_cta_hook_flags_midsentence_gap() -> None:
    assert any(
        "mid-sentence gap" in issue
        for issue in lint_cta_hook("Answer the call to, where the Scourge festers.")
    )
    assert any(
        "mid-sentence gap" in issue
        for issue in lint_cta_hook("Hold the line and contest the and every road.")
    )


def test_finalize_cta_hook_trims_to_complete_sentence() -> None:
    # An over-budget two-sentence hook keeps the first complete sentence instead of
    # chopping the second mid-clause into "...answer the Warchief's."
    hook = (
        "Hunt down the rebel and hold the Forsaken line in a town where the Alliance still "
        "claws at victory; the war for Andorhal hangs on ruthless resolve. Press the campaign "
        "west and answer the Warchief's command before the front collapses."
    )
    out = finalize_cta_hook(hook)
    assert out.endswith((".", "!", "?"))
    assert not out.rstrip(".").endswith("Warchief's")
    assert lint_cta_hook(out) == []


def test_lint_cta_hook_flags_possessive_truncation() -> None:
    assert any(
        "truncated" in issue
        for issue in lint_cta_hook("Press the campaign west and answer the Warchief's.")
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
    assert {row["quest_node_id"] for row in scoped}.issubset(
        {"quest-a", "quest-b", "quest-c", "quest-d"}
    )
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
