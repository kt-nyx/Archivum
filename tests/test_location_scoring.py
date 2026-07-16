from __future__ import annotations

from pipeline.contracts.models import LocationSelectionDecision, LocationSelectionState
from pipeline.discovery.location_discovery import select_profiled_locations
from pipeline.generate.draft.location_scoring import (
    LocationCandidate,
    collect_location_candidates,
    finalize_evidence_pools,
    select_location_cards,
)


def _selection(
    location_id: str,
    name: str,
    *,
    state: str = "selected",
    kind: str = "place",
    profile_source_id: str | None = None,
    zone_record: str = "on_zone",
) -> dict[str, object]:
    return {
        "zone_id": "zone-example",
        "location_id": location_id,
        "name": name,
        "source_link": f"/wiki/{name.replace(' ', '_')}",
        "source_relation": "maps_subregions",
        "state": state,
        "entity_kind": kind,
        "entity_kind_decision_id": f"entity-kind-{location_id.removeprefix('location-')}",
        "zone_record": zone_record,
        "profile_source_id": profile_source_id or f"src-{location_id}",
        "profile_evidence_count": 1,
        "categories": ["Example subzones", "Locations"],
        "reason_codes": ["direct_profile_evidence"],
    }


def _profile(
    location_id: str, name: str, text: str, *, source_id: str | None = None
) -> dict[str, str]:
    return {
        "location_id": location_id,
        "location_name": name,
        "source_id": source_id or f"src-{location_id}",
        "source_title": name,
        "section_role": "lead",
        "snippet": text,
    }


def test_selected_place_uses_only_subject_matched_profile_evidence() -> None:
    location_id = "location-sunspire"
    candidates = collect_location_candidates(
        zone_id="zone-example",
        zone_name="Example Zone",
        location_selection_decisions=[_selection(location_id, "Sunspire")],
        pools={
            "location_pool": [
                _profile(location_id, "Sunspire", "Sunspire stands within Example Zone."),
                _profile("location-other", "Other Place", "Other Place mentions Sunspire."),
            ],
            "location_seed_pool": [],
        },
    )

    assert len(candidates) == 1
    assert [item["source_id"] for item in candidates[0].profile_items] == ["src-location-sunspire"]
    assert select_location_cards(candidates)[0].location_id == location_id


def test_substring_mention_never_becomes_profile_evidence() -> None:
    candidates = collect_location_candidates(
        zone_id="zone-example",
        zone_name="Example Zone",
        location_selection_decisions=[_selection("location-sunspire", "Sunspire")],
        pools={
            "location_pool": [
                _profile("location-other", "Other Place", "Other Place contains the word Sunspire.")
            ],
            "location_seed_pool": [],
        },
    )

    assert candidates == []


def test_unqualified_or_offzone_rows_cannot_consume_rendering_budget() -> None:
    selections = [
        _selection("location-concept", "Mystic Principle", kind="object_or_concept"),
        _selection("location-remote", "Remote Tower", zone_record="off_zone"),
        _selection("location-deferred", "Deferred Hall", state="deferred"),
    ]
    profiles = [
        _profile(str(row["location_id"]), str(row["name"]), "Direct profile evidence.")
        for row in selections
    ]
    candidates = collect_location_candidates(
        zone_id="zone-example",
        zone_name="Example Zone",
        location_selection_decisions=selections,
        pools={"location_pool": profiles, "location_seed_pool": []},
    )

    assert candidates == []


def test_seed_mentions_are_supporting_only_not_a_summary_fallback() -> None:
    candidate = LocationCandidate(
        location_id="location-lantern-bay",
        name="Lantern Bay",
        wiki_url="https://example.invalid/Lantern_Bay",
        profile_items=[_profile("location-lantern-bay", "Lantern Bay", "Direct account.")],
        seed_mentions=[{"snippet": "A zone page mentions Lantern Bay."}],
    )

    assert finalize_evidence_pools(candidate) == [candidate.profile_items]


def test_containment_requires_a_directed_lead_link_not_a_name_overlap() -> None:
    parent = LocationCandidate(
        location_id="location-harbor",
        name="Harbor",
        wiki_url="https://example.invalid/Harbor",
        decision="include",
        zone_relevant=True,
        lore_significant=True,
        profile_items=[{"section_role": "lead", "links": []}],
    )
    independent = LocationCandidate(
        location_id="location-market",
        name="Market",
        wiki_url="https://example.invalid/Market",
        decision="include",
        zone_relevant=True,
        profile_items=[{"section_role": "lead", "snippet": "The market discusses Harbor."}],
    )

    selected = select_location_cards([parent, independent])
    assert {row.location_id for row in selected} == {"location-harbor", "location-market"}


def test_progressive_selection_never_exceeds_remaining_card_capacity() -> None:
    def decision(number: int, state: LocationSelectionState) -> LocationSelectionDecision:
        return LocationSelectionDecision(
            decision_id=f"location-selection-example-{number}",
            zone_id="zone-example",
            location_id=f"location-place-{number}",
            name=f"Place {number}",
            source_link=f"/wiki/Place_{number}",
            source_relation="history" if number % 2 else "maps_subregions",
            candidate_rank=number,
            state=state,
            entity_kind="place",
            entity_kind_decision_id=f"entity-kind-place-{number}",
            zone_record="on_zone",
            profile_source_id=f"src-location-place-{number}",
            profile_evidence_count=1,
        )

    selected = select_profiled_locations(
        [
            *(decision(number, LocationSelectionState.SELECTED) for number in range(6)),
            *(decision(number, LocationSelectionState.PROFILE) for number in range(6, 10)),
        ],
        desired_card_count=8,
    )

    assert sum(row.state is LocationSelectionState.SELECTED for row in selected) == 8
