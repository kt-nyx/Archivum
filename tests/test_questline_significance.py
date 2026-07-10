from __future__ import annotations

from pipeline.discovery.questline_card_polish import render_questline_title
from pipeline.discovery.questline_significance import (
    arc_selection_artifact,
    select_zone_arc_families,
)


def _select(summaries: list[dict], records: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    rows = [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "node_id": node_id,
            "cluster_id": summary["cluster_id"],
            "order_in_cluster": index,
        }
        for summary in summaries
        for index, node_id in enumerate(summary["quest_node_ids"], start=1)
    ]
    return select_zone_arc_families(
        zone_id="zone-example", cluster_summaries=summaries, v3_rows=rows, quest_records=records
    )


def _record(node_id: str, *, location: str = "Harbor", actor: str = "Captain", description: str = "Defend the harbor against raiders and secure the signal tower.", faction: str = "shared") -> dict:
    return {
        "zone_id": "zone-example", "node_id": node_id, "has_questbox": True,
        "previous": [], "next": [], "start_location": location, "start_npc": actor,
        "description": description, "faction": faction,
    }


def test_coherent_multi_node_arc_beats_a_weak_long_fragment() -> None:
    summaries = [
        {"zone_id": "zone-example", "cluster_id": "harbor-arc", "title": "Harbor Defense", "faction": "shared", "quest_node_ids": ["h1", "h2", "h3"]},
        {"zone_id": "zone-example", "cluster_id": "long-fragment", "title": "Loose Errands", "faction": "shared", "quest_node_ids": ["l1", "l2", "l3", "l4", "l5"]},
    ]
    records = [_record(node_id) for node_id in summaries[0]["quest_node_ids"]] + [
        _record(node_id, location="", actor="", description="") for node_id in summaries[1]["quest_node_ids"]
    ]
    candidates, _families, _decisions, selected = _select(summaries, records)
    scores = {row["candidate_id"]: row["coherent_score"] for row in candidates}
    assert scores["harbor-arc"] > scores["long-fragment"]
    assert selected[0] == "harbor-arc"


def test_paired_faction_variants_are_family_first_and_both_are_explained() -> None:
    summaries = [
        {"zone_id": "zone-example", "cluster_id": "shore-alliance", "title": "Shore Campaign (Alliance)", "faction": "alliance", "quest_node_ids": ["a1", "a2"]},
        {"zone_id": "zone-example", "cluster_id": "shore-horde", "title": "Shore Campaign (Horde)", "faction": "horde", "quest_node_ids": ["h1", "h2"]},
    ]
    records = [_record(node_id, faction="alliance") for node_id in ["a1", "a2"]] + [_record(node_id, faction="horde") for node_id in ["h1", "h2"]]
    _candidates, families, decisions, selected = _select(summaries, records)
    assert len(families) == 1
    assert set(selected) == {"shore-alliance", "shore-horde"}
    assert any(row["decision"] == "merge" for row in decisions)
    assert sum(row["decision"] == "include" for row in decisions) == 2


def test_similar_titles_without_campaign_evidence_stay_separate() -> None:
    summaries = [
        {"zone_id": "zone-example", "cluster_id": "north-watch", "title": "Watch", "faction": "shared", "quest_node_ids": ["n1", "n2"]},
        {"zone_id": "zone-example", "cluster_id": "south-watch", "title": "Watch", "faction": "shared", "quest_node_ids": ["s1", "s2"]},
    ]
    records = [_record(node_id, location="North Gate", actor="Warden", description="Stop smugglers at the northern gate.") for node_id in ["n1", "n2"]] + [_record(node_id, location="South Mine", actor="Miner", description="Restore the flooded mine pumps.") for node_id in ["s1", "s2"]]
    _candidates, families, decisions, selected = _select(summaries, records)
    assert len(families) == 2
    assert any(row["decision"] == "keep_separate" and row["adjudication"] is None for row in decisions)
    assert len(selected) == 1
    assert any("duplicate_normalized_variant_label" in row["reason_codes"] for row in decisions)


def test_one_quest_candidate_requires_explicit_high_signal_exception() -> None:
    summary = {"zone_id": "zone-example", "cluster_id": "signal", "title": "Signal at Dawn", "faction": "alliance", "quest_node_ids": ["q1"]}
    candidates, _families, _decisions, selected = _select([summary], [_record("q1", faction="alliance")])
    assert "single_quest_high_signal_exception" in candidates[0]["reason_codes"]
    assert selected == ["signal"]


def test_ambiguous_variant_processing_never_doubles_structured_suffixes() -> None:
    summaries = [
        {"zone_id": "zone-example", "cluster_id": "first", "title": "Beacon Run (Alliance)", "faction": "alliance", "quest_node_ids": ["a1", "a2"]},
        {"zone_id": "zone-example", "cluster_id": "second", "title": "Beacon Run (Alliance)", "faction": "alliance", "quest_node_ids": ["b1", "b2"]},
    ]
    records = [_record(node_id, faction="alliance") for node_id in ["a1", "a2", "b1", "b2"]]
    candidates, _families, decisions, _selected = _select(summaries, records)
    assert all(row["base_title"] == "Beacon Run" for row in candidates)
    assert all(row["faction_variant"] == "alliance" for row in candidates)
    assert any(row["decision"] == "merge" for row in decisions)
    assert (
        render_questline_title(
            {"base_title": candidates[0]["base_title"], "faction_variant": candidates[0]["faction_variant"]}
        )
        == "Beacon Run (Alliance)"
    )


def test_arc_artifact_records_ranking_and_explicit_coverage_gap() -> None:
    summary = {"zone_id": "zone-example", "cluster_id": "signal", "title": "Signal at Dawn", "faction": "alliance", "quest_node_ids": ["q1"]}
    candidates, families, decisions, selected = _select([summary], [_record("q1", faction="alliance")])
    artifact = arc_selection_artifact(
        candidates=candidates,
        families=families,
        decisions=decisions,
        selected_candidate_ids_by_zone={"zone-example": selected},
    )
    assert artifact["family_rankings_by_zone"]["zone-example"]
    assert artifact["coverage"] == [
        {
            "zone_id": "zone-example",
            "status": "insufficient_viable_arc_variants",
            "selected_candidate_ids": ["signal"],
            "attempted_candidate_ids": ["signal"],
            "reason_codes": ["insufficient_viable_arc_variants", "all_candidates_and_exclusions_recorded"],
        }
    ]


def test_missing_quest_record_is_excluded_with_an_auditable_reason() -> None:
    summary = {
        "zone_id": "zone-example",
        "cluster_id": "incomplete-arc",
        "title": "Incomplete Arc",
        "faction": "shared",
        "quest_node_ids": ["known", "missing"],
    }
    candidates, _families, decisions, selected = _select([summary], [_record("known")])
    assert "missing_quest_records" in candidates[0]["reason_codes"]
    assert selected == []
    assert any(
        row["decision"] == "exclude" and row["reason_codes"] == ["missing_quest_records"]
        for row in decisions
    )
