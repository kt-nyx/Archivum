from __future__ import annotations

from pipeline.discovery.adventure_guide import AdventureGuideEntry, AdventureGuideInstance
from pipeline.discovery.instance_bosses import BossCandidate
from pipeline.generate.draft.claim_routing import CLAIM_VIEW_KEY
from pipeline.generate.draft.pages.key_characters import (
    _adventure_guide_entry_framing,
    _build_adventure_guide_framing,
    _synthesis_items_from_pool,
    adventure_guide_overview_framing,
)


def _candidate(name: str) -> BossCandidate:
    return BossCandidate(
        boss_id=f"character-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url=f"https://example/{name}",
        source_section_role="dungeon_journal_edit",
    )


def _ag_item(text: str, *, safe: bool = True) -> dict:
    view = {
        "canonical_evidence_id": "ag-1",
        "source_excerpt": text,
        "source_sentence_indexes": [0],
        "temporal_scope": "entry_state" if safe else "active_storyline_outcome",
        "spoiler_safety": "safe_entry_context" if safe else "active_outcome",
        "claim_text": text,
        "is_claim_view": True,
    }
    return {
        "snippet": text,
        "raw_section_role": "adventure_guide_edit",
        "section_role": "adventure_guide",
        CLAIM_VIEW_KEY: [view],
    }


def test_adventure_guide_framing_returns_matching_blurb() -> None:
    boss_pool = [
        _ag_item("Darkmaster Gandling rules Scholomance as its cruel headmaster."),
        _ag_item("Instructor Chillheart guards the Reliquary's cold vault."),
    ]
    framing = _build_adventure_guide_framing(_candidate("Darkmaster Gandling"), boss_pool)
    assert "Gandling" in framing
    assert "Chillheart" not in framing


def test_adventure_guide_framing_empty_without_entry() -> None:
    boss_pool = [_ag_item("Instructor Chillheart guards the Reliquary's cold vault.")]
    assert _build_adventure_guide_framing(_candidate("Rattlegore"), boss_pool) == ""


def test_adventure_guide_framing_spoiler_filtered() -> None:
    # An unsafe AG sentence is dropped by the safe-sentence reconstruction.
    boss_pool = [_ag_item("Rattlegore is defeated and reassembled.", safe=False)]
    assert _build_adventure_guide_framing(_candidate("Rattlegore"), boss_pool) == ""


def _ag_instance() -> AdventureGuideInstance:
    return AdventureGuideInstance(
        instance_title="Scholomance",
        overview="A school of necromancy.",
        entries=(
            AdventureGuideEntry(
                boss_name="Lilian Voss",
                display_name="Lillian Voss",
                course="Reeducation",
                description="The undead Lilian Voss strangled her father and began a rampage.",
            ),
        ),
    )


def test_adventure_guide_entry_framing_uses_description_only() -> None:
    framing = _adventure_guide_entry_framing(_ag_instance(), "Lilian Voss")
    assert "strangled her father" in framing
    # The encounter Course must never leak into the framing text.
    assert "Reeducation" not in framing


def test_adventure_guide_entry_framing_empty_without_match_or_instance() -> None:
    assert _adventure_guide_entry_framing(_ag_instance(), "Rattlegore") == ""
    assert _adventure_guide_entry_framing(None, "Lilian Voss") == ""


def test_adventure_guide_overview_framing_present_and_partial() -> None:
    assert adventure_guide_overview_framing(_ag_instance()) == "A school of necromancy."
    # No Adventure Guide page, or a page whose intro is empty (only per-boss entries), is a no-op.
    assert adventure_guide_overview_framing(None) == ""
    entries_only = AdventureGuideInstance(instance_title="X", overview="", entries=())
    assert adventure_guide_overview_framing(entries_only) == ""


def test_synthesis_items_use_reconstructed_excerpt_and_dedupe_paragraph() -> None:
    summary_pool = [
        {"canonical_evidence_id": "p1", "snippet": "fragment a", "source_id": "s1"},
        {"canonical_evidence_id": "p1", "snippet": "fragment b", "source_id": "s1"},
        {"canonical_evidence_id": "p2", "snippet": "fragment c", "source_id": "s2"},
    ]
    para_excerpts = {"p1": "Reconstructed paragraph one.", "p2": "Reconstructed paragraph two."}
    items = _synthesis_items_from_pool(summary_pool, para_excerpts)
    # p1's two fragments collapse into one item carrying the reconstructed excerpt.
    assert len(items) == 2
    assert items[0]["snippet"] == "Reconstructed paragraph one."
    assert items[1]["snippet"] == "Reconstructed paragraph two."
    assert items[0]["source_id"] == "s1"


def test_synthesis_items_fall_back_to_fragment_without_excerpt() -> None:
    summary_pool = [{"canonical_evidence_id": "p9", "snippet": "only fragment", "source_id": "s9"}]
    items = _synthesis_items_from_pool(summary_pool, {})
    assert items[0]["snippet"] == "only fragment"
