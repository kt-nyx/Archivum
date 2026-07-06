"""Slice 9: point-of-use temporal adjudication for card pools + one shared exclusion policy."""

from __future__ import annotations

import json

import pytest

from pipeline.generate.draft import point_of_use_temporal
from pipeline.generate.draft.faction_scoring import FactionCandidate
from pipeline.generate.draft.location_scoring import LocationCandidate
from pipeline.generate.draft.pages import cards
from pipeline.generate.draft.pool_policy import (
    EXCLUDED_CARD_POOL_SCOPES,
    filter_card_pool,
    is_excluded_from_card_pool,
    row_has_admissible_item,
)
from pipeline.generate.draft.temporal import (
    ACTIVE_STORYLINE,
    ACTIVE_STORYLINE_OUTCOME,
    AMBIGUOUS_TEMPORAL,
    ENTRY_STATE,
    EXCLUDED_NONCANON,
    POST_ACTIVE_LORE,
    PRE_ENTRY_HISTORY,
    CanonicalEvidenceRecord,
    TemporalClassification,
    adjudicate_pool_items_point_of_use,
)

# --- shared exclusion policy (pool_policy) ------------------------------------------------------


def test_excluded_card_pool_scopes_is_the_four_scope_floor() -> None:
    assert EXCLUDED_CARD_POOL_SCOPES == {
        POST_ACTIVE_LORE,
        ACTIVE_STORYLINE_OUTCOME,
        EXCLUDED_NONCANON,
        AMBIGUOUS_TEMPORAL,
    }


def test_filter_card_pool_drops_excluded_keeps_admissible_and_unscoped() -> None:
    items = [
        {"snippet": "a", "temporal_scope": PRE_ENTRY_HISTORY},
        {"snippet": "b", "temporal_scope": ENTRY_STATE},
        {"snippet": "c", "temporal_scope": ACTIVE_STORYLINE},
        {"snippet": "d", "temporal_scope": ""},  # unscoped is kept
        {"snippet": "e", "temporal_scope": AMBIGUOUS_TEMPORAL},
        {"snippet": "f", "temporal_scope": POST_ACTIVE_LORE},
        {"snippet": "g", "temporal_scope": ACTIVE_STORYLINE_OUTCOME},
        {"snippet": "h", "temporal_scope": EXCLUDED_NONCANON},
    ]
    kept = [item["snippet"] for item in filter_card_pool(items)]
    assert kept == ["a", "b", "c", "d"]


def test_is_excluded_reads_build_meta_scope_when_item_unscoped() -> None:
    item = {"snippet": "x"}
    row = {"build_meta": {"temporal_scope": POST_ACTIVE_LORE}}
    assert is_excluded_from_card_pool(item, row=row) is True
    row_ok = {"build_meta": {"temporal_scope": ENTRY_STATE}}
    assert is_excluded_from_card_pool(item, row=row_ok) is False


def test_row_has_admissible_item() -> None:
    excluded_only = {
        "evidence_items": [
            {"snippet": "a", "temporal_scope": AMBIGUOUS_TEMPORAL},
            {"snippet": "b", "temporal_scope": POST_ACTIVE_LORE},
        ]
    }
    assert row_has_admissible_item(excluded_only) is False
    mixed = {
        "evidence_items": [
            {"snippet": "a", "temporal_scope": AMBIGUOUS_TEMPORAL},
            {"snippet": "b", "temporal_scope": ENTRY_STATE},
        ]
    }
    assert row_has_admissible_item(mixed) is True
    assert row_has_admissible_item({}) is True  # no items -> vacuously admissible


# --- point-of-use worker ------------------------------------------------------------------------


def _ambiguous_record(cid: str, snippet: str, *, source_id: str = "src", field: str = "location_pool"):
    return CanonicalEvidenceRecord(
        canonical_evidence_id=cid,
        subject_id="zone-x",
        subject_type="zone",
        source_id=source_id,
        source_categories=[],
        source_title="Profile",
        snippet=snippet,
        boundary={
            "boundary_id": "b1",
            "entry_state_contract": {"active_expansion": {"label": "Cataclysm", "rank": 3}},
        },
        appearances=[{"field_name": field, "raw_section_role": "lead"}],
        refs=[],
        structural_classifications=[],
        classification=TemporalClassification(AMBIGUOUS_TEMPORAL, 0.3, "profile_context_ambiguous", "b1"),
    )


def _ambiguous_item(cid: str, snippet: str, *, source_id: str = "src") -> dict:
    return {
        "canonical_evidence_id": cid,
        "temporal_scope": AMBIGUOUS_TEMPORAL,
        "snippet": snippet,
        "source_id": source_id,
        "section_role": "lead",
    }


def _fake_llm(scope_by_id: dict[str, str], *, seen: list[str] | None = None):
    def _fn(**kwargs):
        payload = json.loads(kwargs["user_prompt"])
        classifications = []
        for prompt_item in payload["items"]:
            cid = prompt_item["canonical_evidence_id"]
            if seen is not None:
                seen.append(cid)
            classifications.append(
                {
                    "canonical_evidence_id": cid,
                    "temporal_scope": scope_by_id[cid],
                    "history_eligibility": "history_not_applicable",
                    "rationale": "test",
                    "history_rationale": "test",
                    "event_label": "",
                }
            )
        return {"classifications": classifications}

    return _fn


def _enable_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled", lambda: False
    )


def test_worker_adjudicates_ambiguous_and_writes_back(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        _fake_llm({"p-post": POST_ACTIVE_LORE, "p-entry": ENTRY_STATE}),
    )
    record_post = _ambiguous_record("p-post", "A later Fourth-War transit through the town.")
    record_entry = _ambiguous_record("p-entry", "A fortified town the player finds on arrival.")
    item_post = _ambiguous_item("p-post", record_post.snippet)
    item_entry = _ambiguous_item("p-entry", record_entry.snippet)
    records = {"p-post": record_post, "p-entry": record_entry}

    decisions = adjudicate_pool_items_point_of_use([item_post, item_entry], records)

    assert item_post["temporal_scope"] == POST_ACTIVE_LORE
    assert item_entry["temporal_scope"] == ENTRY_STATE
    by_id = {row["canonical_evidence_id"]: row for row in decisions}
    assert by_id["p-post"]["marker"] == "point_of_use"
    assert by_id["p-post"]["prior_temporal_scope"] == AMBIGUOUS_TEMPORAL
    assert by_id["p-post"]["temporal_scope"] == POST_ACTIVE_LORE
    assert by_id["p-post"]["snippet"] == record_post.snippet  # rejected text is auditable
    # The shared policy then drops only the post-active paragraph.
    assert filter_card_pool([item_post, item_entry]) == [item_entry]


def test_worker_is_a_noop_when_llm_disabled(monkeypatch) -> None:
    # Default test env: OpenAI not ready => adjudication disabled. Item keeps its ambiguous scope.
    record = _ambiguous_record("p1", "Some profile paragraph.")
    item = _ambiguous_item("p1", record.snippet)
    called = []
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        lambda **kwargs: called.append(kwargs) or {"classifications": []},
    )
    decisions = adjudicate_pool_items_point_of_use([item], {"p1": record})
    assert decisions == []
    assert item["temporal_scope"] == AMBIGUOUS_TEMPORAL
    assert called == []


def test_worker_skips_items_without_a_registered_record(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        _fake_llm({"known": ENTRY_STATE}, seen=seen),
    )
    known_record = _ambiguous_record("known", "Known ambiguous paragraph.")
    known_item = _ambiguous_item("known", known_record.snippet)
    orphan_item = _ambiguous_item("orphan", "Ambiguous paragraph with no record.")

    adjudicate_pool_items_point_of_use([known_item, orphan_item], {"known": known_record})

    assert seen == ["known"]  # the orphan (no record) is never sent to the LLM
    assert known_item["temporal_scope"] == ENTRY_STATE
    assert orphan_item["temporal_scope"] == AMBIGUOUS_TEMPORAL


def test_worker_leaves_non_ambiguous_items_untouched(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry", _fake_llm({}, seen=seen)
    )
    record = _ambiguous_record("p1", "An entry-state paragraph.")
    record.classification = TemporalClassification(ENTRY_STATE, 0.8, "deterministic_entry", "b1")
    item = {
        "canonical_evidence_id": "p1",
        "temporal_scope": ENTRY_STATE,
        "snippet": record.snippet,
        "source_id": "src",
    }
    assert adjudicate_pool_items_point_of_use([item], {"p1": record}) == []
    assert seen == []
    assert item["temporal_scope"] == ENTRY_STATE


def test_adjudicate_card_pool_records_excluded_flag_to_finalize_trace(monkeypatch) -> None:
    from pipeline.generate.draft import finalize_trace

    _enable_llm(monkeypatch)
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        _fake_llm({"p-post": POST_ACTIVE_LORE, "p-entry": ENTRY_STATE}),
    )
    records = {
        "p-post": _ambiguous_record("p-post", "Later transit paragraph."),
        "p-entry": _ambiguous_record("p-entry", "Current setup paragraph."),
    }
    items = [
        _ambiguous_item("p-post", "Later transit paragraph."),
        _ambiguous_item("p-entry", "Current setup paragraph."),
    ]
    point_of_use_temporal.begin(records)
    finalize_trace.begin("zone-x")
    try:
        point_of_use_temporal.adjudicate_card_pool(items, label="faction.zone-x")
    finally:
        point_of_use_temporal.clear()
        recorded = finalize_trace.drain()

    by_id = {row["canonical_evidence_id"]: row for row in recorded}
    assert all(row["stage"] == "temporal.point_of_use" for row in recorded)
    assert by_id["p-post"]["label"] == "faction.zone-x"
    assert by_id["p-post"]["excluded_from_synthesis"] is True
    assert by_id["p-entry"]["excluded_from_synthesis"] is False


# --- integration through the shared vetting seam (both card builders use it) ---------------------


def test_vet_card_pools_adjudicates_then_filters_and_bounds_cost(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        _fake_llm(
            {"p-post": POST_ACTIVE_LORE, "p-entry": ENTRY_STATE, "p-unelected": ENTRY_STATE},
            seen=seen,
        ),
    )
    records = {
        "p-post": _ambiguous_record("p-post", "Later transit paragraph.", source_id="s1"),
        "p-entry": _ambiguous_record("p-entry", "Current setup paragraph.", source_id="s1"),
        "p-unelected": _ambiguous_record("p-unelected", "Paragraph of an un-elected faction.", source_id="s2"),
    }
    point_of_use_temporal.begin(records)
    try:
        elected = FactionCandidate(
            faction_id="faction-x",
            name="Faction X",
            wiki_url="https://example.test/x",
            profile_items=[
                _ambiguous_item("p-post", "Later transit paragraph.", source_id="s1"),
                _ambiguous_item("p-entry", "Current setup paragraph.", source_id="s1"),
            ],
            seed_mentions=[],
        )
        unelected = FactionCandidate(
            faction_id="faction-y",
            name="Faction Y",
            wiki_url="https://example.test/y",
            profile_items=[_ambiguous_item("p-unelected", "Paragraph of an un-elected faction.", source_id="s2")],
            seed_mentions=[],
        )
        # Only the elected candidate is vetted (the card builders pass just the finalize queue).
        cards._vet_card_pools([elected], label="faction.zone-x")
    finally:
        point_of_use_temporal.clear()

    # The post-active paragraph was resolved then dropped; the entry-state one survives.
    assert [item["temporal_scope"] for item in elected.profile_items] == [ENTRY_STATE]
    # Cost bound: the un-elected candidate's paragraph was never sent to the LLM or re-scoped.
    assert "p-unelected" not in seen
    assert unelected.profile_items[0]["temporal_scope"] == AMBIGUOUS_TEMPORAL


def test_post_active_location_paragraph_never_reaches_the_summary_prompt(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")  # deterministic location synthesis
    _enable_llm(monkeypatch)  # but point-of-use adjudication is explicitly enabled
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        _fake_llm({"p-bfa": POST_ACTIVE_LORE, "p-town": ENTRY_STATE}),
    )
    captured_pools: list[list[dict]] = []

    def _capture_summary(pool, **kwargs):
        captured_pools.append(list(pool))
        return "", []

    monkeypatch.setattr(cards, "synthesize_location_summary", _capture_summary)
    monkeypatch.setattr(cards, "fallback_location_summary", lambda pool, **kwargs: ("", []))

    records = {
        "p-bfa": _ambiguous_record("p-bfa", "A Fourth-War caravan passes through Hearthglen."),
        "p-town": _ambiguous_record("p-town", "Hearthglen is a fortified town the player finds on entry."),
    }
    point_of_use_temporal.begin(records)
    try:
        candidate = LocationCandidate(
            location_id="location-hearthglen",
            name="Hearthglen",
            wiki_url="https://example.test/hearthglen",
            profile_items=[
                _ambiguous_item("p-bfa", "A Fourth-War caravan passes through Hearthglen."),
                _ambiguous_item("p-town", "Hearthglen is a fortified town the player finds on entry."),
            ],
        )
        cards._vet_card_pools([candidate], label="location.zone-x")
        cards._finalize_location_card(
            candidate, zone_name="Example Zone", location_decision_map={}
        )
    finally:
        point_of_use_temporal.clear()

    assert captured_pools, "the location summary prompt should have been built"
    seen_snippets = " ".join(
        item.get("snippet", "") for pool in captured_pools for item in pool
    )
    assert "Fourth-War caravan" not in seen_snippets  # post-active paragraph excluded
    assert "fortified town" in seen_snippets  # vetted entry-state paragraph retained


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
