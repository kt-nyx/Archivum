from __future__ import annotations

import json
from hashlib import sha256

from pipeline.generate.draft.temporal import enrich_evidence_temporal_metadata


def _row(
    field_name: str,
    snippet: str,
    *,
    source_id: str = "src-zone",
    raw_role: str = "history",
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
                "source_title": "Example Zone",
                "snippet": snippet,
                "section_role": raw_role,
                "raw_section_role": raw_role,
                "confidence": 1.0,
            }
        ],
    }


def _enrich_with_claims(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    enriched, _temporal_decisions, claim_decisions = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        run_id="test",
        return_claim_decisions=True,
    )
    return enriched, claim_decisions


def test_same_canonical_paragraph_produces_one_claim_set(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = "The old road was fortified before the current fighting began."
    rows = [
        _row("history_digest", snippet),
        _row("currently_input", snippet),
        _row("at_a_glance_input", snippet),
    ]

    enriched, claim_decisions = _enrich_with_claims(rows)

    assert len(claim_decisions) == 1
    decision = claim_decisions[0]
    assert decision["claim_count"] == 1
    assert {
        appearance["field_name"] for appearance in decision["appearances"]
    } == {"history_digest", "currently_input", "at_a_glance_input"}
    assert {
        row["evidence_items"][0]["canonical_evidence_id"] for row in enriched
    } == {decision["canonical_evidence_id"]}
    assert decision["claims"][0]["canonical_evidence_id"] == decision["canonical_evidence_id"]
    assert decision["claims"][0]["claim_type"] == "other"


def test_different_paragraphs_from_same_source_produce_different_claim_sets(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row(
            "history_digest",
            "The first campaign secured the ruined crossing.",
            source_id="src-shared",
        ),
        _row(
            "history_digest",
            "A later patrol rebuilt the old watch post.",
            source_id="src-shared",
        ),
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    assert len(claim_decisions) == 2
    assert len({row["canonical_evidence_id"] for row in claim_decisions}) == 2
    assert len({row["claims"][0]["claim_id"] for row in claim_decisions}) == 2


def test_claim_ids_are_stable(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row(
            "history_digest",
            "The Argent Dawn neutralized plague cauldrons. The fields slowly recovered.",
        )
    ]

    _first_enriched, first_claim_decisions = _enrich_with_claims(rows)
    _second_enriched, second_claim_decisions = _enrich_with_claims(rows)

    first_ids = [claim["claim_id"] for claim in first_claim_decisions[0]["claims"]]
    second_ids = [claim["claim_id"] for claim in second_claim_decisions[0]["claims"]]
    assert first_ids == second_ids


def test_mixed_paragraph_produces_sentence_level_claims(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row(
            "history_digest",
            (
                "The Cenarion Circle begins healing the fields. "
                "The battle later ends with one faction claiming Andorhal."
            ),
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    claims = claim_decisions[0]["claims"]
    assert [claim["source_sentence_indexes"] for claim in claims] == [[0], [1]]
    assert [claim["claim_text"] for claim in claims] == [
        "The Cenarion Circle begins healing the fields.",
        "The battle later ends with one faction claiming Andorhal.",
    ]
    assert {claim["claim_type"] for claim in claims} == {"event"}


def test_semicolon_heavy_sentence_is_not_semantically_split(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row(
            "history_digest",
            (
                "The Cenarion Circle begins healing the fields; "
                "the battle later ends with one faction claiming Andorhal."
            ),
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    claims = claim_decisions[0]["claims"]
    assert len(claims) == 1
    assert claims[0]["source_sentence_indexes"] == [0]
    assert ";" in claims[0]["claim_text"]
    assert claim_decisions[0]["extraction_mode"] == "sentence_fallback"


def test_claim_decision_rows_are_json_serializable(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    _enriched, claim_decisions = _enrich_with_claims(
        [
            _row(
                "history_digest",
                "Hearthglen served as a fortified settlement that endured the plague.",
                source_id="src-history",
            )
        ]
    )

    encoded = json.dumps(claim_decisions)
    assert claim_decisions  # eligible field produces claim rows
    assert "Hearthglen" in encoded


def test_bulk_pools_keep_deterministic_claims_but_never_call_llm(monkeypatch) -> None:
    """Cost-scoping guard: faction/location/quest_lore route at paragraph level. They keep cheap
    deterministic sentence claims (load-bearing for card survival) but never spend an LLM call,
    even when the LLM is otherwise enabled."""
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled", lambda: False
    )

    def _boom(**_kwargs):
        raise AssertionError("bulk-pool field must not trigger an LLM extraction call")

    monkeypatch.setattr("pipeline.generate.draft.claims._extract_claims_llm", _boom)

    long_mixed = (
        "The Cenarion Circle begins healing the fields after the war; the campaign later ends "
        "with one faction claiming Andorhal and fortifying the broken keeps across the frontier."
    )
    for field in ("location_pool", "faction_pool", "quest_lore"):
        _enriched, claim_decisions = _enrich_with_claims(
            [_row(field, long_mixed, source_id=f"src-{field}")]
        )
        assert claim_decisions, f"{field!r} should still emit deterministic claim rows"
        row = claim_decisions[0]
        assert row["claims"], f"{field!r} should keep deterministic sentence claims"
        assert row["extraction_mode"] != "llm_semantic"
        if row["candidate_reasons"]:
            assert row["extraction_reason"] == "field_not_claim_llm_eligible"


def test_eligible_field_shared_with_bulk_pool_still_extracts(monkeypatch) -> None:
    """A paragraph appearing in BOTH an eligible field and a bulk pool stays in scope (the
    eligible appearance wins), so shared history/faction text keeps claim-level treatment."""
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = "The keep fell during the war and later anchored the faction's frontier."
    _enriched, claim_decisions = _enrich_with_claims(
        [
            _row("history_digest", snippet, source_id="src-shared"),
            _row("faction_pool", snippet, source_id="src-shared"),
        ]
    )
    assert claim_decisions and claim_decisions[0]["claims"]


def test_llm_claim_extraction_splits_mixed_wpl_like_paragraph(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": "The Cenarion Circle helps dispel plague.",
                    "claim_type": "faction_presence",
                    "source_sentence_indexes": [0],
                    "entities": [
                        {
                            "role": "faction",
                            "entity_id": "",
                            "name": "Cenarion Circle",
                        }
                    ],
                    "extraction_reason": "Supported by the first source sentence.",
                },
                {
                    "claim_text": "New life starts emerging in the fields.",
                    "claim_type": "state",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "Supported by the first source sentence.",
                },
                {
                    "claim_text": "War rages at Andorhal and Gahrron's Withering.",
                    "claim_type": "event",
                    "source_sentence_indexes": [1],
                    "entities": [],
                    "extraction_reason": "Supported by the second source sentence.",
                },
                {
                    "claim_text": "The Forsaken gain control of Andorhal.",
                    "claim_type": "event",
                    "source_sentence_indexes": [2],
                    "entities": [],
                    "extraction_reason": "Supported by the third source sentence.",
                },
                {
                    "claim_text": "The Alliance is cast out.",
                    "claim_type": "event",
                    "source_sentence_indexes": [2],
                    "entities": [],
                    "extraction_reason": "Supported by the third source sentence.",
                },
                {
                    "claim_text": "The Scourge presence ends.",
                    "claim_type": "state",
                    "source_sentence_indexes": [2],
                    "entities": [],
                    "extraction_reason": "Supported by the third source sentence.",
                },
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    snippet = (
        "The Cenarion Circle helps dispel the plague, and new life starts "
        "emerging in the fields. War rages at Andorhal and Gahrron's Withering. "
        "The Forsaken gain control of Andorhal, the Alliance is cast out, and "
        "the Scourge presence ends."
    )
    rows = [
        _row("history_digest", snippet),
        _row("currently_input", snippet),
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    decision = claim_decisions[0]
    assert decision["extraction_mode"] == "llm_semantic"
    assert "history_current_shared_paragraph" in decision["candidate_reasons"]
    assert [claim["claim_text"] for claim in decision["claims"]] == [
        "The Cenarion Circle helps dispel plague.",
        "New life starts emerging in the fields.",
        "War rages at Andorhal and Gahrron's Withering.",
        "The Forsaken gain control of Andorhal.",
        "The Alliance is cast out.",
        "The Scourge presence ends.",
    ]
    assert {claim["canonical_evidence_id"] for claim in decision["claims"]} == {
        decision["canonical_evidence_id"]
    }
    assert {tuple(claim["source_sentence_indexes"]) for claim in decision["claims"]} == {
        (0,),
        (1,),
        (2,),
    }


def test_llm_claim_extraction_filters_invented_claims(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": "The Cenarion Circle helps dispel plague.",
                    "claim_type": "faction_presence",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "Grounded in the source.",
                },
                {
                    "claim_text": "Northrend wins a naval war.",
                    "claim_type": "event",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "Invented by test.",
                },
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    rows = [
        _row(
            "history_digest",
            "The Cenarion Circle helps dispel the plague; new life starts emerging.",
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    claims = claim_decisions[0]["claims"]
    assert claim_decisions[0]["extraction_mode"] == "llm_semantic"
    assert [claim["claim_text"] for claim in claims] == [
        "The Cenarion Circle helps dispel plague."
    ]


def test_llm_claim_extraction_rejects_partial_overlap_invention(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": "The Alliance wins a naval war.",
                    "claim_type": "event",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "Only one token overlaps the source.",
                }
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    rows = [
        _row(
            "history_digest",
            "The Alliance is cast out; the old watch post remains abandoned.",
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    decision = claim_decisions[0]
    assert decision["extraction_mode"] == "sentence_fallback"
    assert "naval war" not in json.dumps(decision["claims"])


def test_llm_claim_extraction_uses_emitted_text_for_claim_id(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )
    long_claim = " ".join(["The Cenarion Circle helps dispel plague"] * 12)

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": long_claim,
                    "claim_type": "faction_presence",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "Overlong test claim.",
                }
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    rows = [
        _row(
            "history_digest",
            (
                "The Cenarion Circle helps dispel plague; "
                "The Cenarion Circle helps dispel plague; "
                "The Cenarion Circle helps dispel plague."
            ),
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    claim = claim_decisions[0]["claims"][0]
    payload = {
        "canonical_evidence_id": claim["canonical_evidence_id"],
        "claim_text": " ".join(claim["claim_text"].casefold().split()),
        "source_sentence_indexes": claim["source_sentence_indexes"],
    }
    expected = (
        "claim-"
        + sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[
            :20
        ]
    )
    assert len(claim["claim_text"]) <= 240
    assert claim["claim_id"] == expected


def test_llm_claim_extraction_flags_long_source_passthrough(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )
    sentence = (
        "The Cenarion Circle helps dispel the plague while new life slowly starts emerging "
        "throughout the fields around the ruined farms."
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": sentence,
                    "claim_type": "state",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "Exact source sentence from test.",
                }
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    rows = [_row("history_digest", f"{sentence}; the battle later ends elsewhere.")]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    claim = claim_decisions[0]["claims"][0]
    assert claim["source_passthrough_risk"] is True
    assert claim["source_passthrough_reason"] in {
        "llm_claim_matches_source_sentence",
        "llm_claim_is_long_source_substring",
    }


def test_llm_claim_extraction_filters_invalid_sentence_indexes(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": "The Cenarion Circle helps dispel plague.",
                    "claim_type": "faction_presence",
                    "source_sentence_indexes": [99],
                    "entities": [],
                    "extraction_reason": "Invalid sentence index from test.",
                }
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    rows = [
        _row(
            "history_digest",
            "The Cenarion Circle helps dispel the plague; new life starts emerging.",
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    decision = claim_decisions[0]
    assert decision["extraction_mode"] == "sentence_fallback"
    assert len(decision["claims"]) == 1
    assert decision["claims"][0]["source_sentence_indexes"] == [0]


def test_llm_claim_extraction_backfills_uncovered_sentences(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "claims": [
                {
                    "claim_text": "The Cenarion Circle helps dispel plague.",
                    "claim_type": "faction_presence",
                    "source_sentence_indexes": [0],
                    "entities": [],
                    "extraction_reason": "LLM intentionally missed the second sentence.",
                }
            ]
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fake_llm_json_with_retry,
    )
    snippet = (
        "The Cenarion Circle helps dispel the plague. "
        "The battle later ends with one faction claiming Andorhal."
    )
    rows = [
        _row("history_digest", snippet),
        _row("currently_input", snippet),
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    decision = claim_decisions[0]
    assert decision["extraction_mode"] == "llm_semantic"
    assert decision["sentence_backfill_count"] == 1
    assert [claim["source_sentence_indexes"] for claim in decision["claims"]] == [[0], [1]]
    assert decision["claims"][1]["extraction_reason"] == "sentence_fallback_uncovered_by_llm"


def test_setup_and_outcome_boundary_overlap_marks_candidate(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    snippet = (
        "Scouts gather supplies near the road before the commander claims victory "
        "after the battle."
    )
    rows = [
        _row(
            "questline_pool",
            "Scouts gather supplies near the road.",
            build_meta={"cluster_id": "cluster-1", "quest_node_id": "q1"},
        ),
        _row(
            "questline_pool",
            "The commander claims victory after the battle.",
            build_meta={"cluster_id": "cluster-1", "quest_node_id": "q4"},
        ),
        _row("history_digest", snippet),
    ]

    _enriched, _temporal_decisions, claim_decisions = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        questline_card_metadata={
            "cluster-1": {
                "zone_id": "zone-example",
                "display_title": "Road Campaign",
                "registry_chain_refs": ["q1", "q2", "q3", "q4"],
            }
        },
        quest_records_by_node={
            "q1": {"node_id": "q1", "description": "Scouts gather supplies near the road."},
            "q2": {"node_id": "q2", "description": "Hold the line."},
            "q4": {
                "node_id": "q4",
                "description": "The commander claims victory after the battle.",
            },
        },
        run_id="test",
        return_claim_decisions=True,
    )

    history_decision = next(
        row for row in claim_decisions if row["source_excerpt"] == snippet
    )
    assert "matches_setup_and_outcome_boundary_context" in history_decision["candidate_reasons"]
    assert history_decision["extraction_mode"] == "sentence_fallback"


def test_llm_claim_extraction_failure_uses_sentence_fallback(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        "pipeline.generate.draft.claims._llm_claim_extraction_disabled",
        lambda: False,
    )

    def fail_llm_json_with_retry(**_kwargs):
        raise RuntimeError("provider failure")

    monkeypatch.setattr(
        "pipeline.generate.draft.claims.llm_json_with_retry",
        fail_llm_json_with_retry,
    )
    rows = [
        _row(
            "history_digest",
            "The Cenarion Circle helps dispel plague; the battle later ends.",
        )
    ]

    _enriched, claim_decisions = _enrich_with_claims(rows)

    decision = claim_decisions[0]
    assert decision["extraction_mode"] == "sentence_fallback"
    assert decision["llm_error"] == "RuntimeError"
    assert len(decision["claims"]) == 1


def test_claim_extraction_is_opt_in_for_temporal_enrichment(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [_row("history_digest", "The old road was fortified.")]

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("claim extraction should be opt-in")

    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.extract_canonical_claim_decision_rows",
        fail_if_called,
    )
    outputs = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        run_id="test",
    )

    assert len(outputs) == 2
