from __future__ import annotations

import json

from pipeline.generate.draft.temporal import (
    ACTIVE_MECHANICS_STATE,
    ACTIVE_OUTCOME,
    ACTIVE_STORYLINE_OUTCOME,
    ENTRY_STATE,
    HISTORY_BACKGROUND,
    HISTORY_EXCLUDED_OUTCOME,
    HISTORY_EXCLUDED_POST_ACTIVE,
    HISTORY_SETUP_BRIDGE,
    POST_ACTIVE_LORE,
    POST_ACTIVE_REFERENCE,
    PRE_ENTRY_HISTORY,
    SAFE_BACKGROUND,
    SAFE_ENTRY_CONTEXT,
    CanonicalEvidenceRecord,
    TemporalClassification,
    classify_claims_temporal,
    enrich_evidence_temporal_metadata,
)


def _row(
    field_name: str,
    snippet: str,
    raw_role: str = "history",
    *,
    source_id: str = "src-zone",
    subject_id: str = "zone-example",
    subject_type: str = "zone",
    build_meta: dict | None = None,
) -> dict:
    meta = {
        "run_id": "test",
        "source_id": source_id,
        "raw_section_role": raw_role,
    }
    if build_meta:
        meta.update(build_meta)
    return {
        "subject_id": subject_id,
        "subject_type": subject_type,
        "field_name": field_name,
        "build_meta": meta,
        "evidence_items": [
            {
                "source_url": "https://example.test",
                "source_title": "Example",
                "snippet": snippet,
                "section_role": raw_role,
                "raw_section_role": raw_role,
                "confidence": 1.0,
            }
        ],
    }


def _classification_for_prompt_item(
    item: dict,
    *,
    temporal_scope: str,
    history_eligibility: str,
    rationale: str,
    history_rationale: str,
    event_label: str = "",
) -> dict:
    return {
        "canonical_evidence_id": item["canonical_evidence_id"],
        "temporal_scope": temporal_scope,
        "history_eligibility": history_eligibility,
        "rationale": rationale,
        "history_rationale": history_rationale,
        "event_label": event_label,
    }


def _claim_temporal_for_single_row(
    row: dict,
    monkeypatch,
    *,
    canonical_scope: str,
    canonical_history: str,
    questline_card_metadata: dict | None = None,
    quest_records_by_node: dict | None = None,
) -> dict:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        schema_name = kwargs.get("response_schema_name")
        if schema_name == "wiki_first_temporal_boundary_classification":
            items = json.loads(kwargs["user_prompt"])["items"]
            return {
                "classifications": [
                    _classification_for_prompt_item(
                        item,
                        temporal_scope=canonical_scope,
                        history_eligibility=canonical_history,
                        rationale="Paragraph test classification.",
                        history_rationale="Paragraph history test classification.",
                    )
                    for item in items
                ]
            }
        raise AssertionError(f"unexpected LLM schema {schema_name}")

    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    outputs = enrich_evidence_temporal_metadata(
        [row],
        fact_packs_by_entity={
            str(row["subject_id"]): {
                "entity_id": str(row["subject_id"]),
                "entity_type": str(row["subject_type"]),
                "name": "Example",
            }
        },
        questline_card_metadata=questline_card_metadata,
        quest_records_by_node=quest_records_by_node,
        run_id="test",
        return_claim_decisions=True,
        return_claim_temporal_decisions=True,
    )
    claim_temporal_decisions = outputs[-1]
    return claim_temporal_decisions[0]["claims"][0]


def test_argent_dawn_cauldron_claim_is_pre_entry_history(monkeypatch) -> None:
    claim = _claim_temporal_for_single_row(
        _row("history_digest", "The Argent Dawn neutralized plague cauldrons across the farms."),
        monkeypatch,
        canonical_scope=PRE_ENTRY_HISTORY,
        canonical_history=HISTORY_BACKGROUND,
    )

    assert claim["temporal_scope"] == PRE_ENTRY_HISTORY
    assert claim["history_eligibility"] == HISTORY_BACKGROUND
    assert claim["spoiler_safety"] == SAFE_BACKGROUND


def test_entry_state_setup_claim_is_history_setup_bridge(monkeypatch) -> None:
    claim = _claim_temporal_for_single_row(
        _row("history_digest", "The Cenarion Circle begins healing the fields."),
        monkeypatch,
        canonical_scope=ENTRY_STATE,
        canonical_history=HISTORY_SETUP_BRIDGE,
    )

    assert claim["temporal_scope"] == ENTRY_STATE
    assert claim["history_eligibility"] == HISTORY_SETUP_BRIDGE
    assert claim["spoiler_safety"] == SAFE_ENTRY_CONTEXT


def test_active_storyline_outcome_claim_is_unsafe(monkeypatch) -> None:
    claim = _claim_temporal_for_single_row(
        _row(
            "questline_pool",
            "The Forsaken gain control of Andorhal.",
            "quest",
            build_meta={"cluster_id": "cluster-1", "quest_node_id": "q4"},
        ),
        monkeypatch,
        canonical_scope=ACTIVE_STORYLINE_OUTCOME,
        canonical_history=HISTORY_EXCLUDED_OUTCOME,
        questline_card_metadata={
            "cluster-1": {
                "zone_id": "zone-example",
                "display_title": "Battle for Andorhal",
                "registry_chain_refs": ["q1", "q2", "q3", "q4"],
            }
        },
        quest_records_by_node={
            "q1": {"node_id": "q1", "description": "The battle begins outside Andorhal."},
            "q4": {"node_id": "q4", "description": "The Forsaken gain control of Andorhal."},
        },
    )

    assert claim["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME
    assert claim["history_eligibility"] == HISTORY_EXCLUDED_OUTCOME
    assert claim["spoiler_safety"] == ACTIVE_OUTCOME
    assert "appearance_structural_hint:late_quest_record" in claim["structural_hints"]
    assert "appearance_reason:late_or_overflow_questline_member" in claim["structural_hints"]


def test_later_report_claim_is_post_active(monkeypatch) -> None:
    claim = _claim_temporal_for_single_row(
        _row(
            "history_digest",
            "The Shadow Council later entered Scholomance to seize a book.",
            "later appearances",
            subject_id="instance-example",
            subject_type="instance",
        ),
        monkeypatch,
        canonical_scope=POST_ACTIVE_LORE,
        canonical_history=HISTORY_EXCLUDED_POST_ACTIVE,
    )

    assert claim["temporal_scope"] == POST_ACTIVE_LORE
    assert claim["history_eligibility"] == HISTORY_EXCLUDED_POST_ACTIVE
    assert claim["spoiler_safety"] == POST_ACTIVE_REFERENCE


def test_encounter_state_claim_is_not_safe_character_summary_context(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    outputs = enrich_evidence_temporal_metadata(
        [
            _row(
                "boss_pool",
                "Course: Reeducation appears as an encounter state in the academy.",
                "boss",
                subject_id="instance-example",
                subject_type="instance",
                build_meta={"source_kind": "seed"},
            )
        ],
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Example Instance",
            }
        },
        run_id="test",
        return_claim_temporal_decisions=True,
    )
    claim = outputs[-1][0]["claims"][0]

    assert claim["temporal_scope"] == ENTRY_STATE
    assert claim["spoiler_safety"] == ACTIVE_MECHANICS_STATE


def test_mixed_paragraph_claims_use_claim_level_llm(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    claim_prompt_items = []
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_claim_extraction(**kwargs):
        if kwargs.get("response_schema_name") != "wiki_first_evidence_claim_extraction":
            return None
        return {
            "claims": [
                {
                    "claim_text": "The Cenarion Circle helps dispel plague.",
                    "claim_type": "faction_presence",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "setup claim",
                },
                {
                    "claim_text": "The Forsaken gain control of Andorhal.",
                    "claim_type": "event",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "outcome claim",
                },
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_claim_extraction,
    )

    def fake_temporal_llm(**kwargs):
        schema_name = kwargs.get("response_schema_name")
        if schema_name == "wiki_first_temporal_boundary_classification":
            items = json.loads(kwargs["user_prompt"])["items"]
            return {
                "classifications": [
                    _classification_for_prompt_item(
                        item,
                        temporal_scope=ACTIVE_STORYLINE_OUTCOME,
                        history_eligibility=HISTORY_EXCLUDED_OUTCOME,
                        rationale="Paragraph is mixed but outcome-dominated.",
                        history_rationale="Mixed paragraph is unsafe at paragraph level.",
                    )
                    for item in items
                ]
            }
        if schema_name == "wiki_first_claim_temporal_classification":
            items = json.loads(kwargs["user_prompt"])["items"]
            claim_prompt_items.extend(items)
            return {
                "classifications": [
                    {
                        "claim_id": items[0]["claim_id"],
                        "temporal_scope": ENTRY_STATE,
                        "history_eligibility": HISTORY_SETUP_BRIDGE,
                        "spoiler_safety": SAFE_ENTRY_CONTEXT,
                        "confidence": 0.86,
                        "rationale": "Healing is setup for the current zone state.",
                        "history_rationale": "Setup bridge is history-eligible.",
                        "event_label": "healing setup",
                    },
                    {
                        "claim_id": items[1]["claim_id"],
                        "temporal_scope": ACTIVE_STORYLINE_OUTCOME,
                        "history_eligibility": HISTORY_EXCLUDED_OUTCOME,
                        "spoiler_safety": ACTIVE_OUTCOME,
                        "confidence": 0.91,
                        "rationale": "Control of Andorhal is an outcome.",
                        "history_rationale": "Outcome is excluded.",
                        "event_label": "Andorhal outcome",
                    },
                ]
            }
        raise AssertionError(f"unexpected schema {schema_name}")

    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        fake_temporal_llm,
    )
    snippet = (
        "The Cenarion Circle helps dispel plague; "
        "The Forsaken gain control of Andorhal."
    )
    outputs = enrich_evidence_temporal_metadata(
        [_row("history_digest", snippet), _row("currently_input", snippet)],
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        source_snapshots=[
            {
                "source_id": "src-zone",
                "categories": ["World of Warcraft zones"],
            }
        ],
        run_id="test",
        return_claim_decisions=True,
        return_claim_temporal_decisions=True,
    )
    claim_temporal = outputs[-1][0]

    assert [claim["temporal_scope"] for claim in claim_temporal["claims"][:2]] == [
        ENTRY_STATE,
        ACTIVE_STORYLINE_OUTCOME,
    ]
    assert claim_temporal["paragraph_aggregate"]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME
    assert claim_temporal["paragraph_aggregate"]["history_eligibility"] == HISTORY_EXCLUDED_OUTCOME
    assert claim_prompt_items
    prompt_hints = set(claim_prompt_items[0]["deterministic_hints"])
    assert "raw_section_role:history" in prompt_hints
    assert any(hint.startswith("category_disposition:") for hint in prompt_hints)
    assert any(hint.startswith("paragraph_structural_hint:") for hint in prompt_hints)


def _entry_state_setup_bridge_record(
    canonical_id: str, *, name: str = ""
) -> CanonicalEvidenceRecord:
    paragraph = TemporalClassification(
        scope=ENTRY_STATE,
        confidence=0.84,
        reason="entry-state setup bridge",
        history_eligibility=HISTORY_SETUP_BRIDGE,
        history_reason="states the zone's current setup",
    )
    boundary: dict = {"boundary_id": "boundary-test"}
    if name:
        boundary["entry_state_contract"] = {"name": name}
    return CanonicalEvidenceRecord(
        canonical_evidence_id=canonical_id,
        subject_id="zone-western-plaguelands",
        subject_type="zone",
        source_id="src-wpl",
        source_categories=[],
        source_title="Western Plaguelands",
        snippet="(paragraph snippet)",
        boundary=boundary,
        appearances=[{"field_name": "history_digest"}],
        refs=[],
        structural_classifications=[],
        classification=paragraph,
    )


def _claim(
    claim_id: str, claim_type: str, text: str, entities: list[str], sentences: list[int]
) -> dict:
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "claim_text": text,
        "entities": [{"name": name} for name in entities],
        "source_sentence_indexes": sentences,
    }


def _claim_rows_by_id(decision: dict, record: CanonicalEvidenceRecord) -> dict:
    rows = classify_claims_temporal([decision], [record], run_id="test")
    return {claim["claim_id"]: claim for claim in rows[0]["claims"]}


def test_active_storyline_outcome_excluded_from_setup_bridge_paragraph() -> None:
    # A setup-bridge paragraph that states current conditions ("war still raged in Andorhal") and
    # also resolves the active conflict. The resolution claims must be re-labeled active_storyline_
    # outcome regardless of whether extraction tagged them `event` or `state` (the tag is a
    # nondeterministic coin flip), and every claim in the resolving sentence goes with them; the
    # ongoing-state marker and the setup claims in other sentences stay eligible (clarification Q2).
    canonical_id = "canonical-andorhal"
    record = _entry_state_setup_bridge_record(canonical_id)
    claims = [
        _claim("c0", "state", "The plague was mostly dispelled during the Cataclysm.",
               ["Western Plaguelands"], [0]),
        _claim("c2", "state", "Life started to emerge again in the region.",
               ["Western Plaguelands"], [1]),
        _claim("c3", "encounter_state", "War still raged in Andorhal and Gahrron's Withering.",
               ["Andorhal", "Gahrron's Withering"], [1]),
        _claim("c5", "relationship", "Alliance forces were commanded by Thassarian.",
               ["Alliance", "Thassarian"], [2]),
        # Resolutions tagged as *state* — the wpl-15 coin flip that leaked before the fix widened
        # anchoring/propagation beyond `event`.
        _claim("c7", "state", "The Forsaken gained control of Andorhal.",
               ["Forsaken", "Andorhal"], [2]),
        _claim("c9", "state", "Scourge presence in the Western Plaguelands ended.",
               ["Scourge", "Western Plaguelands"], [2]),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "zone-western-plaguelands",
        "subject_type": "zone",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)

    # safe setup in non-resolving sentences survives, including the ongoing-conflict marker
    for claim_id in ("c0", "c2", "c3"):
        assert by_id[claim_id]["temporal_scope"] == ENTRY_STATE
        assert by_id[claim_id]["history_eligibility"] == HISTORY_SETUP_BRIDGE
    # every claim in the resolving sentence is excluded: the state-tagged resolutions (c7, and the
    # entity-poor "Scourge presence ended" c9 caught by sentence propagation) AND the commander
    # relationship c5, which describes the active battle rather than pre-entry history
    for claim_id in ("c5", "c7", "c9"):
        assert by_id[claim_id]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME
        assert by_id[claim_id]["history_eligibility"] == HISTORY_EXCLUDED_OUTCOME
        assert by_id[claim_id]["spoiler_safety"] == ACTIVE_OUTCOME


def test_subject_name_not_treated_as_contested_locus() -> None:
    # The encounter_state marker lists the zone itself among its entities ("war raged in Andorhal …
    # Western Plaguelands"). The subject's own name and id must be stripped from the contested set,
    # so a safe setup claim that merely names the zone is not swept into the outcome. (wpl-15 bug:
    # the id form of the zone stayed contested and anchored the safe sentences.)
    canonical_id = "canonical-subject-guard"
    record = _entry_state_setup_bridge_record(canonical_id, name="Western Plaguelands")
    claims = [
        _claim("s0", "state", "The plague was mostly dispelled across the Western Plaguelands.",
               ["Western Plaguelands"], [0]),
        _claim("s1", "encounter_state", "War still raged in Andorhal within the Western Plaguelands.",
               ["Andorhal", "Western Plaguelands"], [1]),
        _claim("s2", "state", "The Forsaken gained control of Andorhal.",
               ["Forsaken", "Andorhal"], [2]),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "zone-western-plaguelands",
        "subject_type": "zone",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)

    assert by_id["s0"]["temporal_scope"] == ENTRY_STATE
    assert by_id["s1"]["temporal_scope"] == ENTRY_STATE
    assert by_id["s2"]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME


def test_reclaimed_current_location_event_stays_history_eligible() -> None:
    # Regression guard: a held/reclaimed location (no encounter_state sibling, not an active
    # conflict) must NOT be mistaken for an active-storyline outcome. This is the Hearthglen
    # setup-bridge that Slice 7 requires to remain in history.
    canonical_id = "canonical-hearthglen"
    record = _entry_state_setup_bridge_record(canonical_id)
    claims = [
        _claim("h0", "event", "Hearthglen was reclaimed by Tirion Fordring after the war.",
               ["Hearthglen", "Tirion Fordring"], [0]),
        _claim("h1", "location_status", "The city became the Argent Crusade's main base.",
               ["Hearthglen", "Argent Crusade"], [1]),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "zone-western-plaguelands",
        "subject_type": "zone",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)

    assert by_id["h0"]["temporal_scope"] == ENTRY_STATE
    assert by_id["h0"]["history_eligibility"] == HISTORY_SETUP_BRIDGE
