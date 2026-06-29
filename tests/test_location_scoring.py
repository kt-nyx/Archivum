from __future__ import annotations

from pipeline.generate.draft.location_scoring import (
    MIN_SCORE,
    LocationCandidate,
    collect_location_candidates,
    extract_subregion_tokens,
    location_zone_relevant,
    score_location_candidate,
    select_location_cards,
)
from pipeline.generate.draft.pages.assembly import _build_evidence_pools


def _profile_item(
    location_id: str,
    snippet: str,
    *,
    section_role: str = "history",
    location_name: str = "Northwatch Hold",
) -> dict[str, object]:
    return {
        "location_id": location_id,
        "location_name": location_name,
        "source_id": f"src-{location_id}",
        "snippet": snippet,
        "section_role": section_role,
        "source_title": location_name,
    }


def _seed_item(snippet: str, *, section_role: str = "maps_subregions") -> dict[str, object]:
    return {
        "source_id": "src-zone",
        "snippet": snippet,
        "section_role": section_role,
        "field_name": "history_digest",
    }


def _location_row(location_id: str, name: str, zone_id: str = "zone-example") -> dict[str, str]:
    return {
        "zone_id": zone_id,
        "location_id": location_id,
        "name": name,
        "classification": "major_location_candidate",
        "typing_signals": {"source_section_role": "maps_subregions"},
    }


def _decision(location_id: str, final: str) -> dict[str, object]:
    return {
        "subject_id": location_id,
        "final_decision": final,
        "reason_codes": ["score_based"] if final == "include" else ["defer"],
    }


def _location_candidate(
    location_id: str,
    name: str,
    snippet: str,
    *,
    lore_significant: bool = True,
    source_section_role: str = "history",
) -> LocationCandidate:
    return LocationCandidate(
        location_id=location_id,
        name=name,
        wiki_url=f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
        profile_items=[
            {
                "source_id": f"src-{location_id}",
                "source_title": name,
                "snippet": snippet,
                "section_role": source_section_role,
            }
        ],
        decision="include",
        source_section_role=source_section_role,
        zone_relevant=True,
        lore_significant=lore_significant,
    )


def test_collect_and_select_include_only_locations() -> None:
    zone_id = "zone-example"
    zone_name = "Example Zone"
    location_id = "location-northwatch-hold"
    snippet = (
        "Northwatch Hold is a fortified outpost in Example Zone where alliance patrols "
        "coordinate supply lines and defensive operations across the contested frontier."
    )
    pools = {
        "location_pool": [_profile_item(location_id, snippet, location_name="Northwatch Hold")],
        "location_seed_pool": [
            _seed_item(
                "Northwatch Hold, Broken Ridge, and Sentinel Hill anchor key routes in Example Zone."
            )
        ],
    }
    candidates = collect_location_candidates(
        zone_id=zone_id,
        zone_name=zone_name,
        location_rows=[_location_row(location_id, "Northwatch Hold", zone_id)],
        location_candidate_map={
            location_id: {
                "location_id": location_id,
                "name": "Northwatch Hold",
                "source_link": "/wiki/Northwatch_Hold",
            }
        },
        location_decision_map={
            location_id: _decision(location_id, "include"),
            "location-defer-only": _decision("location-defer-only", "defer"),
        },
        pools=pools,
    )
    selected = select_location_cards(candidates)
    assert len(selected) == 1
    assert selected[0].location_id == location_id
    assert selected[0].score >= MIN_SCORE


def test_location_is_offzone_helper() -> None:
    from pipeline.discovery.entity_typing import location_is_offzone, location_subzone_zone_slugs

    # in-zone: subzone category matches the subject zone
    assert not location_is_offzone(["Western Plaguelands subzones", "Cities"], "zone-western-plaguelands")
    # off-zone: only a different zone's subzone category (Strahnbrad's real case)
    assert location_is_offzone(
        ["Hillsbrad Foothills subzones", "Destroyed settlements", "Villages"],
        "zone-western-plaguelands",
    )
    # no subzone category at all -> no signal, never over-reject
    assert not location_is_offzone(["Temples", "Burial sites"], "zone-western-plaguelands")
    assert not location_is_offzone(None, "zone-western-plaguelands")
    assert location_subzone_zone_slugs(["Hillsbrad Foothills subzones"]) == {"hillsbrad-foothills"}


def test_offzone_location_rejected_by_subzone_category() -> None:
    # An in-zone landmark and an off-zone place (a different zone's subzone, merely linked from this
    # zone's prose) both look electable on score; only the in-zone one should survive.
    zone_id = "zone-example"
    zone_name = "Example Zone"
    in_id, off_id = "location-keep-hold", "location-far-village"
    in_snippet = (
        "Keep Hold is a fortified outpost in Example Zone where patrols coordinate supply lines "
        "and defensive operations across the contested frontier."
    )
    off_snippet = (
        "Far Village is a ruined settlement that Example Zone's history recalls, though it lies "
        "within the neighboring region beyond the frontier."
    )
    candidates = collect_location_candidates(
        zone_id=zone_id,
        zone_name=zone_name,
        location_rows=[
            _location_row(in_id, "Keep Hold", zone_id),
            _location_row(off_id, "Far Village", zone_id),
        ],
        location_candidate_map={
            in_id: {
                "location_id": in_id,
                "name": "Keep Hold",
                "source_link": "/wiki/Keep_Hold",
                "categories": ["Example subzones", "Keeps"],
            },
            off_id: {
                "location_id": off_id,
                "name": "Far Village",
                "source_link": "/wiki/Far_Village",
                "categories": ["Neighboring Region subzones", "Destroyed settlements"],
            },
        },
        location_decision_map={
            in_id: _decision(in_id, "include"),
            off_id: _decision(off_id, "include"),
        },
        pools={
            "location_pool": [
                _profile_item(in_id, in_snippet, location_name="Keep Hold"),
                _profile_item(off_id, off_snippet, location_name="Far Village"),
            ],
            "location_seed_pool": [
                _seed_item("Keep Hold and Far Village both appear in Example Zone's gazetteer."),
            ],
        },
    )
    by_id = {candidate.location_id: candidate for candidate in candidates}
    assert by_id[off_id].rejected
    assert "offzone_subzone_category" in by_id[off_id].reject_reasons
    assert not by_id[in_id].rejected
    selected_ids = {candidate.location_id for candidate in select_location_cards(candidates)}
    assert in_id in selected_ids
    assert off_id not in selected_ids


def test_defer_candidates_are_not_elected() -> None:
    zone_id = "zone-example"
    candidate = score_location_candidate(
        collect_location_candidates(
            zone_id=zone_id,
            zone_name="Example Zone",
            location_rows=[_location_row("location-defer", "Defer Place", zone_id)],
            location_candidate_map={
                "location-defer": {"source_link": "/wiki/Defer_Place", "name": "Defer Place"}
            },
            location_decision_map={"location-defer": _decision("location-defer", "defer")},
            pools={
                "location_pool": [
                    _profile_item(
                        "location-defer",
                        "Defer Place remains a notable landmark within Example Zone and anchors patrol routes.",
                        location_name="Defer Place",
                    )
                ],
                "location_seed_pool": [],
            },
        )[0]
    )
    assert candidate.score == 0.0
    assert not select_location_cards([candidate])


def test_location_zone_relevance_requires_zone_or_subregion() -> None:
    tokens = extract_subregion_tokens(
        [_seed_item("Northwatch Hold, Broken Ridge, and Sentinel Hill in Example Zone.")],
        zone_name="Example Zone",
    )
    assert location_zone_relevant(
        "Northwatch Hold anchors alliance patrol routes.",
        zone_name="Example Zone",
        subregion_tokens=tokens,
    )
    assert not location_zone_relevant(
        "A globally famous capital with no local tie.",
        zone_name="Example Zone",
        subregion_tokens=tokens,
    )


def test_lede_only_profile_with_seed_mentions_remains_electable() -> None:
    zone_id = "zone-example"
    location_id = "location-northwatch-hold"
    pools = {
        "location_pool": [
            _profile_item(
                location_id,
                "Northwatch Hold is a major location located in the region.",
                section_role="lead",
            )
        ],
        "location_seed_pool": [
            _seed_item(
                "Northwatch Hold anchors alliance patrol routes and supply lines across Example Zone."
            )
        ],
    }
    candidates = collect_location_candidates(
        zone_id=zone_id,
        zone_name="Example Zone",
        location_rows=[_location_row(location_id, "Northwatch Hold", zone_id)],
        location_candidate_map={location_id: {"source_link": "/wiki/Northwatch_Hold"}},
        location_decision_map={location_id: _decision(location_id, "include")},
        pools=pools,
    )
    selected = select_location_cards(candidates)
    assert len(selected) == 1
    assert selected[0].lede_only
    assert selected[0].seed_mentions


def test_location_pool_does_not_fall_back_to_history_digest() -> None:
    evidence_rows = [
        {
            "subject_id": "zone-example",
            "field_name": "location_pool",
            "build_meta": {"source_id": "src-profile", "location_id": "location-a"},
            "evidence_items": [
                {"snippet": "Profile-only location evidence.", "section_role": "lead"}
            ],
        },
        {
            "subject_id": "zone-example",
            "field_name": "history_digest",
            "build_meta": {"source_id": "src-zone"},
            "evidence_items": [
                {
                    "snippet": "History-only geography mention for Example Subregion.",
                    "section_role": "maps_subregions",
                }
            ],
        },
    ]
    pools = _build_evidence_pools(evidence_rows)
    assert len(pools["location_pool"]) == 1
    assert pools["location_pool"][0]["snippet"] == "Profile-only location evidence."
    assert len(pools["location_seed_pool"]) == 1
    assert "Example Subregion" in pools["location_seed_pool"][0]["snippet"]


def test_select_location_cards_suppresses_child_keep_when_parent_is_selected() -> None:
    selected = select_location_cards(
        [
            _location_candidate(
                "location-hearthglen",
                "Hearthglen",
                "Hearthglen is a major fortified settlement in Example Zone.",
            ),
            _location_candidate(
                "location-mardenholde-keep",
                "Mardenholde Keep",
                "Mardenholde Keep is a keep within Hearthglen in Example Zone.",
                source_section_role="maps_subregions",
            ),
            _location_candidate(
                "location-caer-darrow",
                "Caer Darrow",
                "Caer Darrow anchors the lake crossing in Example Zone.",
            ),
            _location_candidate(
                "location-uthers-tomb",
                "Uther's Tomb",
                "Uther's Tomb marks a major memorial in Example Zone.",
            ),
        ]
    )
    names = [candidate.name for candidate in selected]

    assert "Hearthglen" in names
    assert "Mardenholde Keep" not in names
