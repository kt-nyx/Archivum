from __future__ import annotations

import json

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


def test_claim_decision_rows_are_json_serializable(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    _enriched, claim_decisions = _enrich_with_claims(
        [
            _row(
                "location_pool",
                "Hearthglen serves as a fortified settlement.",
                source_id="src-location",
                build_meta={
                    "location_id": "location-hearthglen",
                    "location_name": "Hearthglen",
                },
            )
        ]
    )

    encoded = json.dumps(claim_decisions)
    assert "location_status" in encoded
    assert "location-hearthglen" in encoded


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
