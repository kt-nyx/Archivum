from __future__ import annotations

from pipeline.contracts.models import EntityKind, LocationSelectionState
from pipeline.discovery.location_discovery import (
    build_location_candidate_decision,
    location_candidate_rank,
    profile_establishes_zone_record,
)


def test_candidate_rank_uses_source_relationship_not_title_shape() -> None:
    assert location_candidate_rank("history", "Small Hut") < location_candidate_rank(
        "maps_subregions", "Grand Citadel"
    )


def test_unknown_target_remains_a_probe_candidate() -> None:
    row = build_location_candidate_decision(
        zone_id="zone-example",
        location_id="location-unresolved-lead",
        name="Unresolved Lead",
        source_link="/wiki/Unresolved_Lead",
        source_relation="geography",
        candidate_rank=0,
        entity_kind=EntityKind.UNKNOWN,
        entity_kind_decision_id="entity-kind-unresolved-lead",
        source_ids=["src-zone"],
        reason_codes=["insufficient_target_evidence"],
    )

    assert row.state is LocationSelectionState.CANDIDATE


def test_known_concept_is_rejected_before_profile_budget() -> None:
    row = build_location_candidate_decision(
        zone_id="zone-example",
        location_id="location-abstract-principle",
        name="Abstract Principle",
        source_link="/wiki/Abstract_Principle",
        source_relation="history",
        candidate_rank=0,
        entity_kind=EntityKind.OBJECT_OR_CONCEPT,
        entity_kind_decision_id="entity-kind-abstract-principle",
        source_ids=["src-zone"],
        reason_codes=["affirmative_target_evidence"],
    )

    assert row.state is LocationSelectionState.REJECTED
    assert "entity_kind_not_place" in row.reason_codes


def test_zone_record_requires_the_profile_page_to_name_its_zone() -> None:
    assert profile_establishes_zone_record(
        {"body": "The landmark lies in Example Zone.", "section_blocks": []}, "Example Zone"
    )
    assert not profile_establishes_zone_record(
        {"body": "The landmark lies beyond the frontier.", "section_blocks": []}, "Example Zone"
    )
