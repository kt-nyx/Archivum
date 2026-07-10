from __future__ import annotations

from pipeline.common.draft_vocab import expansion_release_order
from pipeline.generate.draft.temporal import (
    AMBIGUOUS_TEMPORAL,
    CanonicalEvidenceRecord,
    TemporalClassification,
    _active_expansion_rank,
    _canonical_prompt_item,
    _derive_active_expansion,
    _expansion_rank_for_role,
    _expansion_recency,
    _paragraph_expansion_rank,
    _temporal_adjudication_system_prompt,
)


def test_release_order_is_chronological_and_includes_midnight() -> None:
    order = expansion_release_order()
    assert "midnight" in order
    # chronology: classic < cataclysm < legion < war_within < midnight
    ranks = {token: index for index, token in enumerate(order)}
    assert ranks["classic"] < ranks["cataclysm"] < ranks["legion"] < ranks["war_within"]
    assert ranks["war_within"] < ranks["midnight"]


def test_expansion_rank_for_role_matches_edit_stems() -> None:
    assert _expansion_rank_for_role("legion_edit") is not None
    assert _expansion_rank_for_role("mists_of_pandaria_edit") is not None
    assert _expansion_rank_for_role("battle_for_azeroth_edit") is not None
    assert _expansion_rank_for_role("the_war_within_edit") is not None
    # legion is later than the mop redesign era
    assert _expansion_rank_for_role("legion_edit") > _expansion_rank_for_role("mists_of_pandaria_edit")
    # structural (non-expansion) sections are unranked
    assert _expansion_rank_for_role("adventure_guide_edit") is None
    assert _expansion_rank_for_role("exploring_azeroth_edit") is None
    assert _expansion_rank_for_role("lead") is None


def test_expansion_recency_compares_ranks() -> None:
    mop = _expansion_rank_for_role("mists_of_pandaria_edit")
    legion = _expansion_rank_for_role("legion_edit")
    cata = _expansion_rank_for_role("cataclysm_edit")
    assert _expansion_recency(legion, mop) == "later"
    assert _expansion_recency(cata, mop) == "earlier"
    assert _expansion_recency(mop, mop) == "same"
    assert _expansion_recency(None, mop) == "unknown"
    assert _expansion_recency(legion, None) == "unknown"


def _record(*, raw_section_role: str, active_rank: int | None) -> CanonicalEvidenceRecord:
    contract: dict = {"name": "Scholomance"}
    if active_rank is not None:
        contract["active_expansion"] = {"label": "mists", "rank": active_rank}
    return CanonicalEvidenceRecord(
        canonical_evidence_id="canonical-x",
        subject_id="instance-scholomance",
        subject_type="instance",
        source_id="src",
        source_categories=[],
        source_title="Scholomance",
        snippet="During the third invasion of the Burning Legion the Shadow Council came for the book.",
        boundary={"boundary_id": "b", "entry_state_contract": contract},
        appearances=[{"field_name": "history_digest", "raw_section_role": raw_section_role}],
        refs=[],
        structural_classifications=[],
        classification=TemporalClassification(AMBIGUOUS_TEMPORAL, 0.0, "prior"),
    )


def test_paragraph_expansion_rank_from_appearances() -> None:
    record = _record(raw_section_role="legion_edit", active_rank=None)
    assert _paragraph_expansion_rank(record) == _expansion_rank_for_role("legion_edit")


def test_active_expansion_rank_read_from_contract() -> None:
    record = _record(raw_section_role="legion_edit", active_rank=4)
    assert _active_expansion_rank(record.boundary) == 4


def test_prompt_item_includes_expansion_recency_later() -> None:
    # Legion paragraph vs a MoP active-content expansion -> the classifier sees recency=later.
    mop_rank = _expansion_rank_for_role("mists_of_pandaria_edit")
    record = _record(raw_section_role="legion_edit", active_rank=mop_rank)
    item = _canonical_prompt_item(record)
    assert item["expansion_recency"] == "later"


def test_prompt_item_recency_unknown_without_active_expansion() -> None:
    record = _record(raw_section_role="legion_edit", active_rank=None)
    assert _canonical_prompt_item(record)["expansion_recency"] == "unknown"


def test_derive_active_expansion_is_explicitly_unknown_when_llm_disabled(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        {
            "field_name": "at_a_glance_input",
            "evidence_items": [{"snippet": "Redesigned in the expansion Mists of Pandaria."}],
        }
    ]
    decision = _derive_active_expansion(
        rows,
        name="Example Site",
        source_anchor_refs=[
            {
                "kind": "questline_setup",
                "metadata_id": "metadata-ql-example",
                "setup_quest_refs": ["quest-entry"],
                "setup_snippets": ["The wardens prepare the current defense."],
            }
        ],
    )
    assert decision["status"] == "unknown"
    assert decision["fallbacks"] == ["active_expansion_adjudication_unavailable"]


def test_rubric_documents_expansion_recency() -> None:
    prompt = _temporal_adjudication_system_prompt(canonical=True)
    assert "expansion_recency" in prompt
    assert "soft prior toward post_active_lore" in prompt
    # Slice 3 tempering: 'later' with no contract linkage needs strong textual evidence to be
    # current setup — while the chronology-is-not-the-question framing stays.
    assert "The key question is not" in prompt
    assert "requires strong textual evidence" in prompt
    assert "entry_state or history_setup_bridge" in prompt
