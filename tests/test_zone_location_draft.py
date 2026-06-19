from __future__ import annotations

from pipeline.discovery.entity_typing import should_reject_location_title
from pipeline.generate.draft.location_lint import lint_location_summary
from pipeline.generate.draft.pages import build_zone_page


def _fact_pack(zone_id: str) -> dict[str, object]:
    return {
        "entity_id": zone_id,
        "name": "Example Zone",
        "source_ids": ["src-zone", "src-location-northwatch", "src-location-defer"],
        "revision_ids": ["mw:1", "mw:2", "mw:3"],
        "source_urls": {
            "src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone",
            "src-location-northwatch": "https://warcraft.wiki.gg/wiki/Northwatch_Hold",
            "src-location-defer": "https://warcraft.wiki.gg/wiki/Defer_Place",
        },
    }


def _minimal_prose_evidence(zone_id: str) -> list[dict[str, object]]:
    return [
        {
            "subject_id": zone_id,
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": (
                        "A contested frontier where patrols and druids resist undead remnants "
                        "across ruined farmland and broken keeps throughout Example Zone."
                    ),
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "snippet": (
                        "Recovery efforts continue to reshape roads and outposts while patrols "
                        "push back undead forces along the main road through Example Zone."
                    ),
                    "section_role": "cataclysm_edit",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "snippet": (
                        "The region was devastated during the invasion and fell under undead control "
                        "for decades before military campaigns began restoring order across the frontier, "
                        "broken keeps, and scattered villages throughout Example Zone."
                    ),
                    "section_role": "history",
                },
                {
                    "snippet": (
                        "Northwatch Hold, Broken Ridge, and Sentinel Hill anchor key routes in Example Zone."
                    ),
                    "section_role": "maps_subregions",
                },
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
    ]


def _location_evidence(zone_id: str) -> list[dict[str, object]]:
    northwatch_snippet = (
        "Northwatch Hold is a fortified outpost in Example Zone where alliance patrols coordinate "
        "supply lines, defensive operations, and regional scouting missions across the frontier."
    )
    defer_snippet = (
        "Defer Place is a minor waypoint in Example Zone that appears in travel notes but lacks "
        "major narrative significance for zone-level landmark cards."
    )
    return [
        {
            "subject_id": zone_id,
            "field_name": "location_pool",
            "build_meta": {
                "source_id": "src-location-northwatch",
                "subject_zone_id": zone_id,
                "location_id": "location-northwatch-hold",
                "location_name": "Northwatch Hold",
            },
            "evidence_items": [{"snippet": northwatch_snippet, "section_role": "history"}],
        },
        {
            "subject_id": zone_id,
            "field_name": "location_pool",
            "build_meta": {
                "source_id": "src-location-defer",
                "subject_zone_id": zone_id,
                "location_id": "location-defer-place",
                "location_name": "Defer Place",
            },
            "evidence_items": [{"snippet": defer_snippet, "section_role": "lead"}],
        },
    ]


def _location_rows(zone_id: str) -> list[dict[str, object]]:
    return [
        {
            "zone_id": zone_id,
            "location_id": "location-northwatch-hold",
            "name": "Northwatch Hold",
            "classification": "major_location_candidate",
            "typing_signals": {"source_section_role": "maps_subregions"},
        },
        {
            "zone_id": zone_id,
            "location_id": "location-defer-place",
            "name": "Defer Place",
            "classification": "major_location_candidate",
            "typing_signals": {"source_section_role": "other"},
        },
    ]


def _location_candidate_map(zone_id: str) -> dict[str, dict[str, object]]:
    return {
        "location-northwatch-hold": {
            "zone_id": zone_id,
            "location_id": "location-northwatch-hold",
            "name": "Northwatch Hold",
            "source_link": "/wiki/Northwatch_Hold",
        },
        "location-defer-place": {
            "zone_id": zone_id,
            "location_id": "location-defer-place",
            "name": "Defer Place",
            "source_link": "/wiki/Defer_Place",
        },
    }


def _location_decisions() -> dict[str, dict[str, object]]:
    return {
        "location-northwatch-hold": {
            "subject_id": "location-northwatch-hold",
            "final_decision": "include",
            "reason_codes": ["score_based"],
        },
        "location-defer-place": {
            "subject_id": "location-defer-place",
            "final_decision": "defer",
            "reason_codes": ["defer"],
        },
    }


def test_build_zone_page_emits_include_only_location_cards_without_llm(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence = _minimal_prose_evidence(zone_id) + _location_evidence(zone_id)
    draft = build_zone_page(
        _fact_pack(zone_id),
        evidence,
        [],
        _location_rows(zone_id),
        [],
        _location_candidate_map(zone_id),
        _location_decisions(),
        None,
        location_profile_targets=[
            {
                "zone_id": zone_id,
                "location_id": "location-northwatch-hold",
                "name": "Northwatch Hold",
                "source_link": "/wiki/Northwatch_Hold",
                "source_section_role": "maps_subregions",
            }
        ],
    )
    cards = draft.get("location_cards") or []
    assert cards
    ids = [str(row.get("id", "")) for row in cards]
    assert "location-northwatch-hold" in ids
    assert "location-defer-place" not in ids
    reject, _ = should_reject_location_title("Third War (28 ADP)")
    assert reject
    for card in cards:
        summary = str(card.get("summary", ""))
        assert summary
        assert not lint_location_summary(
            summary,
            zone_name="Example Zone",
            location_name=str(card.get("name", "")),
        )


def test_build_zone_page_uses_seed_pool_when_profile_summary_fails_lint(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    seed_snippet = (
        "Northwatch Hold is a fortified outpost in Example Zone where alliance patrols coordinate "
        "supply lines, defensive operations, and regional scouting missions across the frontier."
    )
    prose = _minimal_prose_evidence(zone_id)
    for row in prose:
        if row.get("field_name") == "history_digest":
            items = row.get("evidence_items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("section_role") == "maps_subregions":
                        item["snippet"] = seed_snippet
    evidence = prose + [
        {
            "subject_id": zone_id,
            "field_name": "location_pool",
            "build_meta": {
                "source_id": "src-location-northwatch",
                "subject_zone_id": zone_id,
                "location_id": "location-northwatch-hold",
                "location_name": "Northwatch Hold",
            },
            "evidence_items": [
                {
                    "snippet": "Northwatch Hold is a major location located in the region.",
                    "section_role": "lead",
                }
            ],
        },
    ]
    draft = build_zone_page(
        _fact_pack(zone_id),
        evidence,
        [],
        _location_rows(zone_id),
        [],
        _location_candidate_map(zone_id),
        _location_decisions(),
        None,
        location_profile_targets=[
            {
                "zone_id": zone_id,
                "location_id": "location-northwatch-hold",
                "name": "Northwatch Hold",
                "source_link": "/wiki/Northwatch_Hold",
                "source_section_role": "maps_subregions",
            }
        ],
    )
    cards = draft.get("location_cards") or []
    assert len(cards) == 1
    summary = str(cards[0].get("summary", ""))
    assert "Example Zone" in summary
    assert "major location located" not in summary.lower()
    assert not lint_location_summary(
        summary,
        zone_name="Example Zone",
        location_name="Northwatch Hold",
    )
