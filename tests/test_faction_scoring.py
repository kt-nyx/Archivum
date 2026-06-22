from __future__ import annotations

from pipeline.generate.draft.faction_scoring import (
    ALLIANCE_HORDE_CONFLICT_THRESHOLD,
    MIN_SCORE,
    collect_faction_candidates,
    fallback_faction_summary,
    score_faction_candidate,
    select_major_factions,
)

_NAVBOX_SNIPPET = (
    "Plaguelands Western Plaguelands The Bulwark Chillwind Camp Hearthglen Menders' Stead "
    "Northridge Lumber Camp Eastern Plaguelands Light's Hope Chapel Sanctum of Light "
    "Tyr's Hand Scarlet Bastion Crown Guard Tower Eastwall Tower Northpass Tower"
)
_PROSE_SNIPPET = (
    "The Argent Crusade holds the Bulwark and presses its campaign against the Scourge "
    "across the Western Plaguelands, reclaiming Hearthglen for the living."
)


def test_fallback_faction_summary_skips_navbox_for_prose() -> None:
    # #2: the (zone-hit, word_count) ranking prefers the longer navbox; the list guard must
    # skip it and elect the genuine prose snippet instead.
    items = [
        {"snippet": _NAVBOX_SNIPPET, "source_id": "src-navbox"},
        {"snippet": _PROSE_SNIPPET, "source_id": "src-prose"},
    ]
    summary, sources = fallback_faction_summary(items, zone_name="Western Plaguelands")
    assert "Argent Crusade" in summary
    assert "Chillwind Camp Hearthglen" not in summary
    assert sources == ["src-prose"]


def test_fallback_faction_summary_returns_empty_when_only_navbox() -> None:
    items = [{"snippet": _NAVBOX_SNIPPET, "source_id": "src-navbox"}]
    summary, sources = fallback_faction_summary(items, zone_name="Western Plaguelands")
    assert summary == ""
    assert sources == []


def _profile_item(
    faction_id: str,
    snippet: str,
    *,
    section_role: str = "lead",
    source_id: str = "src-faction",
) -> dict[str, object]:
    return {
        "faction_id": faction_id,
        "source_id": source_id,
        "snippet": snippet,
        "section_role": section_role,
        "source_title": faction_id.removeprefix("faction-").replace("-", " ").title(),
    }


def _seed_item(snippet: str, *, section_role: str = "quests_edit") -> dict[str, object]:
    return {
        "source_id": "src-zone",
        "snippet": snippet,
        "section_role": section_role,
        "field_name": "currently_input",
    }


def _target(faction_id: str, name: str, zone_id: str = "zone-example") -> dict[str, str]:
    return {
        "zone_id": zone_id,
        "faction_id": faction_id,
        "name": name,
        "source_link": f"/wiki/{name.replace(' ', '_')}",
    }


def _evidence_faction_pack(
    zone_id: str,
    faction_id: str,
    faction_name: str,
    snippet: str,
) -> dict[str, object]:
    return {
        "subject_id": zone_id,
        "field_name": "faction_pool",
        "build_meta": {
            "subject_zone_id": zone_id,
            "faction_id": faction_id,
            "faction_name": faction_name,
            "source_id": f"src-{faction_id}",
        },
        "evidence_items": [{"snippet": snippet, "section_role": "lead"}],
    }


def test_collect_faction_candidates_from_targets_and_evidence() -> None:
    zone_id = "zone-example"
    targets = [
        _target("faction-argent-crusade", "Argent Crusade"),
        _target("faction-cenarion-circle", "Cenarion Circle"),
    ]
    evidence = [
        _evidence_faction_pack(
            zone_id,
            "faction-argent-crusade",
            "Argent Crusade",
            "The Argent Crusade maintains fortified outposts across the contested frontier.",
        )
    ]
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-argent-crusade",
                "The Argent Crusade maintains fortified outposts across the contested frontier.",
            )
        ],
        "faction_role_pool": [],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=evidence,
        pools=pools,
        faction_profile_targets=targets,
    )
    ids = {row.faction_id for row in candidates}
    assert ids == {"faction-argent-crusade", "faction-cenarion-circle"}


def test_currently_input_counts_as_high_weight_seed() -> None:
    from pipeline.generate.draft.faction_scoring import _is_high_weight_seed_item

    assert _is_high_weight_seed_item(
        {
            "snippet": "Alliance patrols continue along the main road.",
            "section_role": "lead",
            "field_name": "currently_input",
        }
    )


def test_alliance_excluded_without_conflict_signal() -> None:
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-argent-crusade",
                (
                    "The Argent Crusade maintains fortified outposts and coordinates "
                    "reclamation efforts against undead forces throughout the zone."
                ),
                section_role="history",
            )
        ],
        "faction_role_pool": [
            {
                "source_id": "src-zone",
                "snippet": "The Alliance maintains a small presence near the border outpost.",
                "section_role": "history",
                "field_name": "history_digest",
            },
            _seed_item(
                "Argent Crusade patrols continue to push back undead forces along the main road.",
                section_role="quests_edit",
            ),
        ],
    }
    targets = [
        _target("faction-alliance", "Alliance"),
        _target("faction-argent-crusade", "Argent Crusade"),
    ]
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=targets,
    )
    alliance = next(row for row in candidates if row.faction_id == "faction-alliance")
    scored_alliance = score_faction_candidate(alliance)
    assert scored_alliance.score <= 1.0
    elected = select_major_factions(candidates)
    elected_ids = {row.faction_id for row in elected}
    assert "faction-argent-crusade" in elected_ids
    assert "faction-alliance" not in elected_ids


def test_alliance_included_with_quest_bindings() -> None:
    zone_id = "zone-example"
    v3_rows = [
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "alliance"},
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "alliance"},
    ]
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-alliance",
                (
                    "Alliance forces coordinate reclamation patrols along the main road "
                    "while securing supply lines across the contested frontier."
                ),
                section_role="history",
            )
        ],
        "faction_role_pool": [],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=[_target("faction-alliance", "Alliance")],
        v3_rows=v3_rows,
    )
    scored = score_faction_candidate(candidates[0])
    assert scored.quest_binding_count >= ALLIANCE_HORDE_CONFLICT_THRESHOLD
    assert scored.score >= MIN_SCORE
    elected = select_major_factions(candidates)
    assert any(row.faction_id == "faction-alliance" for row in elected)


def test_select_major_factions_ranks_by_score() -> None:
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-argent-crusade",
                (
                    "The Argent Crusade maintains fortified outposts and coordinates "
                    "reclamation efforts against undead forces throughout Example Zone."
                ),
            ),
            _profile_item(
                "faction-cenarion-circle",
                (
                    "The Cenarion Circle sends druids to heal blighted soil in Example Zone and push back corruption "
                    "along the frontier while supporting crusader campaigns across the region."
                ),
                section_role="history",
            ),
        ],
        "faction_role_pool": [
            _seed_item(
                "Argent Crusade patrols continue to push back undead forces along the main road.",
                section_role="quests_edit",
            ),
        ],
    }
    targets = [
        _target("faction-argent-crusade", "Argent Crusade"),
        _target("faction-cenarion-circle", "Cenarion Circle"),
    ]
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=targets,
    )
    elected = select_major_factions(candidates, zone_name="Example Zone")
    assert len(elected) >= 2
    assert elected[0].faction_id == "faction-argent-crusade"
    assert elected[0].score >= elected[1].score


def test_seed_mentions_used_when_faction_profiles_exist() -> None:
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-argent-crusade",
                "The Argent Crusade is a faction in Azeroth.",
                section_role="lead",
            )
        ],
        "faction_role_pool": [
            _seed_item(
                "Argent Crusade patrols continue to push back undead forces along the main road.",
                section_role="quests_edit",
            ),
        ],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=[_target("faction-argent-crusade", "Argent Crusade")],
    )
    argent = next(row for row in candidates if row.faction_id == "faction-argent-crusade")
    assert argent.seed_mentions
    scored = score_faction_candidate(argent)
    assert scored.score >= MIN_SCORE
    assert scored.has_high_weight_seed


def test_lede_only_profile_excluded_without_seed_or_bindings() -> None:
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-minor-order",
                "The Minor Order is a small faction in Azeroth.",
                section_role="lead",
            )
        ],
        "faction_role_pool": [],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=[_target("faction-minor-order", "Minor Order")],
    )
    scored = score_faction_candidate(candidates[0])
    assert scored.lede_only
    assert scored.score == 0.0
    elected = select_major_factions(candidates)
    assert all(row.faction_id != "faction-minor-order" for row in elected)


def test_seed_only_target_discovered_from_high_weight_mention() -> None:
    zone_id = "zone-example"
    pools = {
        "faction_pool": [],
        "faction_role_pool": [
            _seed_item(
                "Argent Crusade patrols continue to push back undead forces along the main road.",
                section_role="quests_edit",
            ),
        ],
    }
    targets = [_target("faction-argent-crusade", "Argent Crusade")]
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=targets,
    )
    assert any(row.faction_id == "faction-argent-crusade" for row in candidates)
    argent = next(row for row in candidates if row.faction_id == "faction-argent-crusade")
    assert argent.seed_mentions
    assert score_faction_candidate(argent).score >= MIN_SCORE
