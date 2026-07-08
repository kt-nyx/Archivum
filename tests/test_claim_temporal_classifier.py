from __future__ import annotations

import json

from pipeline.generate.draft.temporal import (
    ACTIVE_MECHANICS_STATE,
    ACTIVE_OUTCOME,
    ACTIVE_STORYLINE_OUTCOME,
    AMBIGUOUS_TEMPORAL,
    ENTRY_STATE,
    HISTORY_BACKGROUND,
    HISTORY_EXCLUDED_OUTCOME,
    HISTORY_EXCLUDED_POST_ACTIVE,
    HISTORY_NOT_APPLICABLE,
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


def _llm_setup_bridge_record_with_active_conflict(
    canonical_id: str, *, conflict_label: str, fallback_mode: str
) -> CanonicalEvidenceRecord:
    paragraph = TemporalClassification(
        scope=ENTRY_STATE,
        confidence=0.84,
        reason="entry-state setup bridge",
        fallback_mode=fallback_mode,
        history_eligibility=HISTORY_SETUP_BRIDGE,
        history_reason="standing setup: the antagonist now holds this site",
    )
    boundary: dict = {
        "boundary_id": "boundary-test",
        "entry_state_contract": {
            "name": "Scholomance",
            "active_conflicts": [{"label": conflict_label}],
        },
    }
    return CanonicalEvidenceRecord(
        canonical_evidence_id=canonical_id,
        subject_id="instance-scholomance",
        subject_type="instance",
        source_id="src-scholomance",
        source_categories=[],
        source_title="Scholomance",
        snippet="(paragraph snippet)",
        boundary=boundary,
        appearances=[{"field_name": "history_digest"}],
        refs=[],
        structural_classifications=[],
        classification=paragraph,
    )


def test_llm_setup_bridge_paragraph_survives_global_conflict_match() -> None:
    # Scholomance/Gandling: the page's LLM boundary pass judged the whole paragraph standing setup
    # (history_setup_bridge). A claim that merely NAMES a globally-contested locus ("failed at
    # Andorhal, retreated here to bide his time") while describing who now holds THIS site must not
    # be relabeled an active-storyline outcome by the broad global active-conflict contract match.
    # No encounter_state sibling exists, so the only would-be anchor is that global match.
    canonical_id = "canonical-gandling-holdout"
    record = _llm_setup_bridge_record_with_active_conflict(
        canonical_id, conflict_label="Andorhal", fallback_mode="llm_boundary"
    )
    claims = [
        _claim(
            "g0",
            "event",
            "After failing to take control of Andorhal, Gandling retreated back into "
            "Scholomance to bide his time.",
            ["Darkmaster Gandling", "Andorhal", "Scholomance"],
            [0],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["g0"]["temporal_scope"] == ENTRY_STATE
    assert by_id["g0"]["history_eligibility"] == HISTORY_SETUP_BRIDGE


def test_deterministic_setup_bridge_still_relabels_global_conflict_resolution() -> None:
    # Guard the narrowness of the exception: only a *considered LLM* setup-bridge judgment outranks
    # the global active-conflict match. A merely deterministic setup-bridge label does not, so a
    # genuine resolution of a globally-contested locus is still excluded from history.
    canonical_id = "canonical-det-resolution"
    record = _llm_setup_bridge_record_with_active_conflict(
        canonical_id, conflict_label="Andorhal", fallback_mode="deterministic"
    )
    claims = [
        _claim(
            "d0",
            "state",
            "The Forsaken gained control of Andorhal.",
            ["Forsaken", "Andorhal"],
            [0],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["d0"]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME
    assert by_id["d0"]["history_eligibility"] == HISTORY_EXCLUDED_OUTCOME


def _llm_verdict_record_with_active_conflict(
    canonical_id: str,
    *,
    conflict_label: str,
    confidence: float,
    history_eligibility: str = HISTORY_BACKGROUND,
) -> CanonicalEvidenceRecord:
    """A confident/unconfident llm_boundary ENTRY_STATE paragraph without setup-bridge eligibility."""
    paragraph = TemporalClassification(
        scope=ENTRY_STATE,
        confidence=confidence,
        reason="entry-state paragraph",
        fallback_mode="llm_boundary",
        history_eligibility=history_eligibility,
        history_reason="paragraph describes the standing state of the site",
    )
    boundary: dict = {
        "boundary_id": "boundary-test",
        "entry_state_contract": {
            "name": "Scholomance",
            "active_conflicts": [{"label": conflict_label}],
        },
    }
    return CanonicalEvidenceRecord(
        canonical_evidence_id=canonical_id,
        subject_id="instance-scholomance",
        subject_type="instance",
        source_id="src-scholomance",
        source_categories=[],
        source_title="Scholomance",
        snippet="(paragraph snippet)",
        boundary=boundary,
        appearances=[{"field_name": "history_digest"}],
        refs=[],
        structural_classifications=[],
        classification=paragraph,
    )


def test_confident_llm_paragraph_verdict_defers_global_match_beyond_setup_bridge() -> None:
    # Phase 3 generalization: ANY confident llm_boundary paragraph verdict — not only a
    # history_setup_bridge one — outranks the global active-conflict entity match. The paragraph
    # here is confident entry-state background; a claim naming the contested locus must not be
    # deterministically flipped to an active-storyline outcome.
    canonical_id = "canonical-llm-verdict-general"
    record = _llm_verdict_record_with_active_conflict(
        canonical_id, conflict_label="Andorhal", confidence=0.84
    )
    claims = [
        _claim(
            "v0",
            "event",
            "After failing to take control of Andorhal, Gandling retreated back into "
            "Scholomance to bide his time.",
            ["Darkmaster Gandling", "Andorhal", "Scholomance"],
            [0],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["v0"]["temporal_scope"] == ENTRY_STATE


def test_unconfident_llm_paragraph_verdict_does_not_defer_global_match() -> None:
    # An llm_boundary verdict the model itself was unsure about (ambiguous-tier confidence) is not
    # authoritative: the global active-conflict match still relabels the resolving claim.
    canonical_id = "canonical-llm-verdict-unsure"
    record = _llm_verdict_record_with_active_conflict(
        canonical_id, conflict_label="Andorhal", confidence=0.5
    )
    claims = [
        _claim(
            "u0",
            "state",
            "The Forsaken gained control of Andorhal.",
            ["Forsaken", "Andorhal"],
            [0],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "history_digest"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["u0"]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME


def test_claim_scope_divergence_from_paragraph_is_recorded() -> None:
    # Disagreement telemetry: a claim whose final scope diverges from its canonical paragraph
    # verdict carries a paragraph_scope_divergence record, so deterministic reversions are
    # auditable in the decisions sidecar rather than silent.
    canonical_id = "canonical-divergence"
    record = _entry_state_setup_bridge_record(canonical_id, name="Western Plaguelands")
    claims = [
        _claim("t0", "state", "The plague was mostly dispelled across the region.",
               ["Western Plaguelands"], [0]),
        _claim("t1", "encounter_state", "War still raged in Andorhal.",
               ["Andorhal"], [1]),
        _claim("t2", "state", "The Forsaken gained control of Andorhal.",
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

    # t2 was deterministically relabeled away from the paragraph's entry_state verdict → recorded.
    assert by_id["t2"]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME
    divergence = by_id["t2"]["paragraph_scope_divergence"]
    assert divergence["paragraph_scope"] == ENTRY_STATE
    assert divergence["claim_fallback_mode"] == "deterministic"
    # Claims agreeing with the paragraph verdict carry no divergence marker.
    assert "paragraph_scope_divergence" not in by_id["t0"]
    assert "paragraph_scope_divergence" not in by_id["t1"]


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


# --- Character-biography spoiler classification (self-encounter, guard, LLM escalation) ---


def _character_bio_record(
    canonical_id: str,
    *,
    character_id: str,
    character_name: str,
    confidence: float = 0.86,
    active_encounters: list[dict] | None = None,
    active_conflicts: list[dict] | None = None,
    active_expansion: dict | None = None,
    raw_role: str = "",
) -> CanonicalEvidenceRecord:
    """A deterministic entry_state character-profile paragraph, with roster/contract context.

    ``refs`` carry the profiled character's provenance (``character_id``/``character_name``) exactly
    as a real character_pool row does, so the self-exclusion reads identity from structure.
    """
    paragraph = TemporalClassification(
        scope=ENTRY_STATE,
        confidence=confidence,
        reason="entry structural role",
        fallback_mode="deterministic",
        history_eligibility=HISTORY_NOT_APPLICABLE,
    )
    contract: dict = {"name": "Scholomance"}
    if active_encounters is not None:
        contract["active_encounters"] = active_encounters
    if active_conflicts is not None:
        contract["active_conflicts"] = active_conflicts
    if active_expansion is not None:
        contract["active_expansion"] = active_expansion
    boundary = {"boundary_id": "boundary-test", "entry_state_contract": contract}
    appearance = {
        "field_name": "character_pool",
        "raw_section_role": raw_role,
        "section_role": raw_role,
    }
    ref = {
        "field_name": "character_pool",
        "build_meta": {"character_id": character_id, "character_name": character_name},
    }
    return CanonicalEvidenceRecord(
        canonical_evidence_id=canonical_id,
        subject_id="instance-scholomance",
        subject_type="instance",
        source_id="src-scholomance-profile",
        source_categories=[],
        source_title=character_name,
        snippet="(paragraph snippet)",
        boundary=boundary,
        appearances=[appearance],
        refs=[ref],
        structural_classifications=[],
        classification=paragraph,
    )


def test_active_conflict_contract_match_excludes_self_terms() -> None:
    # Fix 1 unit: a claim that only names the profiled character (who is also an instance encounter)
    # must not read as resolving the conflict; a different encounter it names still anchors.
    from pipeline.generate.draft.temporal import _claim_matches_active_conflict_contract

    boundary = {
        "entry_state_contract": {
            "active_encounters": [
                {"label": "Lilian Voss", "character_id": "character-lilian-voss"},
                {"label": "Darkmaster Gandling", "character_id": "character-darkmaster-gandling"},
            ]
        }
    }
    self_claim = _claim(
        "x", "event", "Lilian Voss began a campaign against the Scarlet Crusade.",
        ["Lilian Voss", "Scarlet Crusade"], [0],
    )
    assert _claim_matches_active_conflict_contract(self_claim, boundary) is True
    assert (
        _claim_matches_active_conflict_contract(
            self_claim, boundary, exclude_terms={"lilian voss"}
        )
        is False
    )
    cross_claim = _claim(
        "y", "event", "Lilian Voss struck down Darkmaster Gandling.",
        ["Lilian Voss", "Darkmaster Gandling"], [0],
    )
    assert (
        _claim_matches_active_conflict_contract(
            cross_claim, boundary, exclude_terms={"lilian voss"}
        )
        is True
    )


def test_profiled_character_terms_read_from_character_pool_provenance() -> None:
    # Fix 1 unit: identity comes from the character_pool ref build_meta, never prose.
    from pipeline.generate.draft.temporal import _profiled_character_terms

    record = _character_bio_record(
        "canonical-terms", character_id="character-lilian-voss", character_name="Lilian Voss"
    )
    terms = _profiled_character_terms(record)
    assert "lilian voss" in terms
    # A record with no character_pool ref yields nothing to exclude.
    assert _profiled_character_terms(_entry_state_setup_bridge_record("canonical-none")) == set()


def test_character_self_encounter_bio_stays_entry_state() -> None:
    # Fix 1 + Fix 2 integrated (the Lilian case): the profiled character is a Scholomance encounter,
    # so every biographical sentence names her. Her backstory must not be swept into an active
    # outcome and filtered as a spoiler.
    canonical_id = "canonical-lilian-bio"
    record = _character_bio_record(
        canonical_id,
        character_id="character-lilian-voss",
        character_name="Lilian Voss",
        active_encounters=[{"label": "Lilian Voss", "character_id": "character-lilian-voss"}],
    )
    claims = [
        _claim(
            "b0", "event",
            "Lilian Voss began a single-minded campaign against the Scarlet Crusade.",
            ["Lilian Voss", "Scarlet Crusade"], [0],
        ),
        _claim(
            "b1", "state", "Lilian Voss was the daughter of High Priest Voss.",
            ["Lilian Voss", "High Priest Voss"], [1],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "character_pool"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["b0"]["temporal_scope"] == ENTRY_STATE
    assert by_id["b1"]["temporal_scope"] == ENTRY_STATE


def test_cross_encounter_outcome_in_character_bio_still_excluded() -> None:
    # Fix 1 does not over-suppress: with the confidence too low for the setup-verdict guard to
    # defer, a claim naming a different encounter still resolves to an active-storyline outcome.
    canonical_id = "canonical-cross-bio"
    record = _character_bio_record(
        canonical_id,
        character_id="character-lilian-voss",
        character_name="Lilian Voss",
        confidence=0.6,
        active_encounters=[
            {"label": "Lilian Voss", "character_id": "character-lilian-voss"},
            {"label": "Darkmaster Gandling", "character_id": "character-darkmaster-gandling"},
        ],
    )
    claims = [
        _claim(
            "c0", "event", "Lilian Voss struck down Darkmaster Gandling.",
            ["Lilian Voss", "Darkmaster Gandling"], [0],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "character_pool"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["c0"]["temporal_scope"] == ACTIVE_STORYLINE_OUTCOME


def test_confident_deterministic_character_bio_defers_global_conflict_match() -> None:
    # Fix 2: a confident deterministic entry read of a character biography defers the weak global
    # active-conflict match (parallel to the LLM-verdict deferral), so a backstory sentence that
    # merely names a contested locus is not flipped to an outcome. Non-character (history_digest)
    # paragraphs still relabel - see test_deterministic_setup_bridge_still_relabels_global_conflict.
    canonical_id = "canonical-bio-global"
    record = _character_bio_record(
        canonical_id,
        character_id="character-lilian-voss",
        character_name="Lilian Voss",
        confidence=0.86,
        active_conflicts=[{"label": "Scarlet Crusade"}],
    )
    claims = [
        _claim(
            "g0", "event",
            "Lilian Voss began a single-minded campaign against the Scarlet Crusade.",
            ["Lilian Voss", "Scarlet Crusade"], [0],
        ),
    ]
    decision = {
        "canonical_evidence_id": canonical_id,
        "subject_id": "instance-scholomance",
        "subject_type": "instance",
        "claims": claims,
        "appearances": [{"field_name": "character_pool"}],
    }
    by_id = _claim_rows_by_id(decision, record)
    assert by_id["g0"]["temporal_scope"] == ENTRY_STATE


def test_character_biography_untagged_escalates_to_llm() -> None:
    # Fix 4: an untagged character-profile paragraph the deterministic pass kept as entry_state only
    # from roster presence - with no expansion tag to date it - is escalated to the boundary LLM.
    from pipeline.generate.draft.temporal import _character_biography_needs_llm

    record = _character_bio_record(
        "canonical-untagged",
        character_id="character-lilian-voss",
        character_name="Lilian Voss",
        active_expansion={"label": "Cataclysm", "rank": 3},
        raw_role="",
    )
    escalated = _character_biography_needs_llm(record)
    assert escalated is not None
    assert escalated.scope == AMBIGUOUS_TEMPORAL
    assert escalated.fallback_mode == "needs_llm"


def test_character_biography_expansion_tagged_not_escalated() -> None:
    # A tagged bio paragraph is datable by the deterministic recency floor, so it is NOT escalated.
    from pipeline.generate.draft.temporal import _character_biography_needs_llm

    record = _character_bio_record(
        "canonical-tagged",
        character_id="character-lilian-voss",
        character_name="Lilian Voss",
        active_expansion={"label": "Cataclysm", "rank": 3},
        raw_role="shadowlands",
    )
    assert _character_biography_needs_llm(record) is None


def test_non_character_paragraph_not_escalated() -> None:
    # Fix 4 is scoped to character biographies: a zone history paragraph is never escalated.
    from pipeline.generate.draft.temporal import _character_biography_needs_llm

    assert _character_biography_needs_llm(_entry_state_setup_bridge_record("canonical-zone")) is None
