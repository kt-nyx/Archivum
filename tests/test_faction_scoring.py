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


def test_fallback_faction_summary_prefers_subject_mentioning_snippet() -> None:
    # A longer, zone-dense snippet that never names the faction must lose to a shorter one that
    # actually describes it — borrowing the former filled an Alliance card with Cenarion text.
    off_subject = (
        "Despite being where the plague first took hold, the Western Plaguelands recovered better "
        "than the east, and the Cenarion Circle nursed much of the land back during the Cataclysm."
    )
    on_subject = (
        "The Alliance holds the Western Plaguelands and defends the ruined city of Andorhal "
        "against the Forsaken."
    )
    items = [
        {"snippet": off_subject, "source_id": "src-off"},
        {"snippet": on_subject, "source_id": "src-on"},
    ]
    summary, sources = fallback_faction_summary(
        items, zone_name="Western Plaguelands", faction_name="Alliance"
    )
    assert "Alliance" in summary
    assert sources == ["src-on"]


def test_fallback_faction_summary_prefers_lint_and_gate_passing_snippet() -> None:
    from pipeline.generate.draft.faction_lint import lint_faction_summary
    from pipeline.generate.draft.prose_gate import prose_gate_rejects

    # First (longest, zone-dense) snippet clears the lint but trips the prose gate; the fallback
    # must skip it for a snippet that clears BOTH, so the deterministic path yields a card the
    # finalizer accepts rather than dropping the faction to [].
    gate_tripping = (
        "On Azeroth, the abominations were created by Kel'Thuzad, and as such are mainly "
        "found in the Scourge's and Forsaken ranks across the world at large."
    )
    clean = "In Scholomance the Scourge maintains the academy and guards its dark halls."
    items = [
        {"snippet": gate_tripping, "source_id": "src-gate"},
        {"snippet": clean, "source_id": "src-clean"},
    ]
    summary, sources = fallback_faction_summary(
        items, zone_name="Scholomance", subregion_tokens=["Caer Darrow"]
    )
    assert summary
    assert not lint_faction_summary(summary, zone_name="Scholomance")
    assert not prose_gate_rejects(summary)
    assert sources == ["src-clean"]


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


def test_generic_horde_suppressed_when_forsaken_elected() -> None:
    # Forsaken (a Horde sub-faction with strong zone presence) makes the generic "Horde" umbrella
    # redundant; the card list should name the concrete actor and drop "Horde", which also frees a
    # slot for the Alliance.
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-forsaken",
                "The Forsaken control Andorhal in Example Zone after driving out the Alliance.",
                section_role="history",
            ),
            _profile_item(
                "faction-horde",
                "The Horde maintains a presence across Example Zone.",
                section_role="history",
            ),
            _profile_item(
                "faction-alliance",
                "Alliance forces hold territory and patrol Example Zone's main road.",
                section_role="history",
            ),
        ],
        "faction_role_pool": [],
    }
    v3_rows = [
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "horde"},
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "horde"},
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "alliance"},
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "alliance"},
    ]
    targets = [
        _target("faction-forsaken", "Forsaken"),
        _target("faction-horde", "Horde"),
        _target("faction-alliance", "Alliance"),
    ]
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=targets,
        v3_rows=v3_rows,
    )
    elected_ids = {row.faction_id for row in select_major_factions(candidates, zone_name="Example Zone")}
    assert "faction-forsaken" in elected_ids
    assert "faction-alliance" in elected_ids
    assert "faction-horde" not in elected_ids


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


def test_high_weight_current_mentions_discover_missing_faction_targets() -> None:
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-redpine-tribe",
                "The Redpine tribe is a small local group near Example Zone.",
                section_role="history",
            )
        ],
        "faction_role_pool": [
            _seed_item(
                (
                    "In Example Zone, the Argent Crusade and Cenarion Circle press on with "
                    "efforts to cleanse and restore the land."
                ),
                section_role="cataclysm_edit",
            )
        ],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=[_target("faction-redpine-tribe", "Redpine tribe")],
    )
    elected = select_major_factions(candidates, zone_name="Example Zone")
    elected_ids = [row.faction_id for row in elected]

    assert "faction-argent-crusade" in elected_ids
    assert "faction-cenarion-circle" in elected_ids
    assert elected_ids.index("faction-argent-crusade") < elected_ids.index("faction-redpine-tribe")
