from __future__ import annotations

from pipeline.generate.draft.pages.zone import build_zone_page


def _fact_pack() -> dict[str, object]:
    return {
        "entity_id": "zone-example",
        "entity_type": "zone",
        "name": "Example Zone",
        "source_ids": ["src-zone", "src-location-sunspire"],
        "source_urls": {
            "src-zone": "https://example.invalid/Example_Zone",
            "src-location-sunspire": "https://example.invalid/Sunspire",
        },
    }


def _evidence() -> list[dict[str, object]]:
    return [
        {
            "subject_id": "zone-example",
            "field_name": "at_a_glance_input",
            "build_meta": {"source_id": "src-zone"},
            "evidence_items": [{"snippet": "Example Zone is a contested frontier.", "section_role": "lead"}],
        },
        {
            "subject_id": "zone-example",
            "field_name": "history_digest",
            "build_meta": {"source_id": "src-zone"},
            "evidence_items": [{"snippet": "The frontier changed through repeated campaigns.", "section_role": "history"}],
        },
        {
            "subject_id": "zone-example",
            "field_name": "location_pool",
            "build_meta": {
                "source_id": "src-location-sunspire",
                "location_id": "location-sunspire",
                "location_name": "Sunspire",
            },
            "evidence_items": [
                {
                    "snippet": "Sunspire is a fortified landmark in Example Zone guarding the eastern road.",
                    "section_role": "lead",
                }
            ],
        },
    ]


def _selection() -> list[dict[str, object]]:
    return [
        {
            "zone_id": "zone-example",
            "location_id": "location-sunspire",
            "name": "Sunspire",
            "source_link": "/wiki/Sunspire",
            "source_relation": "maps_subregions",
            "state": "selected",
            "entity_kind": "place",
            "entity_kind_decision_id": "entity-kind-sunspire",
            "zone_record": "on_zone",
            "profile_source_id": "src-location-sunspire",
            "profile_evidence_count": 1,
            "categories": ["Example subzones", "Landmarks"],
            "reason_codes": ["direct_profile_evidence"],
        }
    ]


def test_zone_page_does_not_render_selected_row_when_profile_identity_is_missing() -> None:
    evidence = _evidence()
    evidence[2]["build_meta"] = {"source_id": "src-unrelated", "location_id": "location-other"}
    draft = build_zone_page(
        _fact_pack(), evidence, [], _selection(), [], {}, {"location-sunspire": _selection()[0]}, None
    )

    assert draft["location_cards"] == []
