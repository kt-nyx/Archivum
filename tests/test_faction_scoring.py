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


def test_fallback_faction_summary_uses_faction_centered_sentence_window() -> None:
    snippet = (
        "Following the Second War in 6 ADP, the fortress at Caer Darrow was restored. "
        "After decades of rule, the Barovs made a deal with Kel'Thuzad, leader of the Cult of the Damned. "
        "The once opulent keep of Caer Darrow secretly became the horrific Scholomance, a school of necromancy."
    )
    summary, sources = fallback_faction_summary(
        [{"snippet": snippet, "source_id": "src-cult"}],
        zone_name="Scholomance",
        subregion_tokens=["Caer Darrow"],
        faction_name="Cult of the Damned",
    )

    assert "Cult of the Damned" in summary
    assert "Scholomance" in summary
    assert "6 ADP" not in summary
    assert sources == ["src-cult"]


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
    clean = (
        "In Scholomance the Scourge maintains the academy, guards its dark halls, and trains "
        "new necromancers to spread the plague beyond Caer Darrow."
    )
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


def _seed_item(
    snippet: str,
    *,
    section_role: str = "quests_edit",
    links: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "source_id": "src-zone",
        "snippet": snippet,
        "section_role": section_role,
        "field_name": "currently_input",
        "links": links or [],
    }


def _link(name: str) -> dict[str, str]:
    return {"anchor_text": name, "href": f"/wiki/{name.replace(' ', '_')}"}


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


def test_active_combatant_outranks_history_only_faction() -> None:
    # Slice A reweight: a faction bound to its own side's current quest campaign (an active
    # belligerent) must outrank a faction whose relevance is purely historical/profile, even when the
    # latter has zone-hit seed mentions. Generic factions no longer borrow score from the shared/
    # neutral quest bindings that every faction in the zone matches.
    zone_id = "zone-example"
    v3_rows = [
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "alliance"} for _ in range(6)
    ] + [{"zone_id": zone_id, "node_type": "quest", "faction_binding": "shared"} for _ in range(8)]
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-old-order",
                "The Old Order once held fortresses across Example Zone during the war.",
                section_role="history",
            ),
        ],
        "faction_role_pool": [
            {
                "source_id": "src-zone",
                "snippet": (
                    "The Old Order is remembered across Example Zone for its historic campaigns "
                    "against the Scourge along the frontier."
                ),
                "section_role": "history",
                "field_name": "history_digest",
            },
        ],
    }
    targets = [
        _target("faction-alliance", "Alliance"),
        _target("faction-old-order", "Old Order"),
    ]
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=targets,
        v3_rows=v3_rows,
    )
    alliance = next(row for row in candidates if row.faction_id == "faction-alliance")
    old = next(row for row in candidates if row.faction_id == "faction-old-order")
    # the lore faction gets no quest credit from the 8 shared quests; the belligerent owns its 6
    assert old.specific_quest_binding_count == 0
    assert alliance.specific_quest_binding_count == 6
    scored_alliance = score_faction_candidate(alliance, zone_name="Example Zone")
    scored_old = score_faction_candidate(old, zone_name="Example Zone")
    assert scored_alliance.score > scored_old.score
    elected_ids = [row.faction_id for row in select_major_factions(candidates, zone_name="Example Zone")]
    assert "faction-alliance" in elected_ids


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
    # Slice 13: Forsaken's Horde membership comes from its crawled profile page's infobox
    # Affiliation field (the org registry's category affiliations only cover gameplay
    # reputation factions), so the suppression needs the profile snapshot.
    snapshots = [
        {
            "auxiliary_role": "faction_profile",
            "auxiliary_target_id": "faction-forsaken",
            "infobox": {"_title": "The Forsaken", "Affiliation": "Horde , Cult of Forgotten Shadows"},
        }
    ]
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=targets,
        v3_rows=v3_rows,
        snapshots=snapshots,
    )
    forsaken = next(row for row in candidates if row.faction_id == "faction-forsaken")
    assert "horde" in forsaken.affiliations
    # Membership also grants the member its side's quest bindings (horde-bound quests).
    assert forsaken.specific_quest_binding_count == 2
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


def test_lede_only_with_shared_bindings_only_is_still_excluded() -> None:
    # Review fix (slice A): shared/neutral quest bindings — which every faction in the zone matches —
    # are not real involvement. A lede-only profile lacking its own seed mentions and side-specific
    # bindings must still be zeroed, even in a zone full of shared quests (where the old
    # quest_binding_count was nonzero and wrongly spared it).
    zone_id = "zone-example"
    v3_rows = [
        {"zone_id": zone_id, "node_type": "quest", "faction_binding": "shared"} for _ in range(8)
    ]
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
        v3_rows=v3_rows,
    )
    scored = score_faction_candidate(candidates[0])
    assert scored.quest_binding_count >= 8  # it does match the zone's shared quests
    assert scored.specific_quest_binding_count == 0  # but owns none of its own side
    assert scored.score == 0.0
    assert all(
        row.faction_id != "faction-minor-order" for row in select_major_factions(candidates)
    )


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
                # Slice 13: identities come from the block's inline links resolved
                # against the org registry, never from prose phrase shapes.
                links=[_link("Argent Crusade"), _link("Cenarion Circle")],
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


def test_resolve_canonical_faction_name_strips_umbrella_qualifier() -> None:
    from pipeline.generate.draft.faction_scoring import resolve_canonical_faction_name

    # RC5: adjacent article links render as one phrase ("[Horde] [Forsaken]"); the member faction
    # is the canonical identity.
    assert resolve_canonical_faction_name("Horde Forsaken") == "Forsaken"
    # Non-umbrella names and the umbrellas themselves are untouched.
    assert resolve_canonical_faction_name("Scarlet Crusade") == "Scarlet Crusade"
    assert resolve_canonical_faction_name("Horde") == "Horde"
    # An umbrella followed by a non-faction word is not resolved.
    assert resolve_canonical_faction_name("Alliance forces") == "Alliance forces"


def test_variant_faction_candidates_merge_onto_canonical_survivor() -> None:
    # Two alias candidates for one faction: the canonical "Forsaken" (from a profile target) and
    # the "Horde Forsaken" variant (e.g. from a stored target that predates phrase resolution).
    # They must collapse to ONE candidate carrying both evidence pools.
    zone_id = "zone-example"
    pools = {
        "faction_pool": [
            _profile_item(
                "faction-forsaken",
                "The Forsaken are renegade undead who broke from the Scourge's control.",
            ),
            _profile_item(
                "faction-horde-forsaken",
                "The Forsaken hold Andorhal in Example Zone after the battle.",
                source_id="src-variant",
            ),
        ],
        "faction_role_pool": [],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=[
            _target("faction-forsaken", "Forsaken"),
            _target("faction-horde-forsaken", "Horde Forsaken"),
        ],
    )
    forsaken_like = [row for row in candidates if "forsaken" in row.faction_id]
    assert len(forsaken_like) == 1
    survivor = forsaken_like[0]
    assert survivor.faction_id == "faction-forsaken"
    assert survivor.name == "Forsaken"
    # The variant's pooled evidence merged onto the survivor (richer card).
    merged_sources = {str(item.get("source_id", "")) for item in survivor.profile_items}
    assert "src-variant" in merged_sources


def test_variant_without_canonical_sibling_renamed_to_canonical() -> None:
    zone_id = "zone-example"
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools={"faction_pool": [], "faction_role_pool": []},
        faction_profile_targets=[_target("faction-horde-forsaken", "Horde Forsaken")],
    )
    assert [row.faction_id for row in candidates] == ["faction-forsaken"]
    assert candidates[0].name == "Forsaken"
    assert candidates[0].wiki_url.endswith("/wiki/Forsaken")


def test_seed_mention_harvest_never_mints_adjacent_link_compound() -> None:
    # Slice 13: wiki prose renders adjacent article links as one phrase ("the [Horde]
    # [Forsaken] hold Andorhal"), but link-based harvesting resolves each link's TARGET,
    # so a "Horde Forsaken" compound identity is structurally impossible.
    zone_id = "zone-example"
    pools = {
        "faction_pool": [],
        "faction_role_pool": [
            _seed_item(
                "War rages in the west as the Horde Forsaken hold the ruined city of Andorhal.",
                links=[_link("Horde"), _link("Forsaken")],
            )
        ],
    }
    candidates = collect_faction_candidates(
        zone_id=zone_id,
        evidence_rows=[],
        pools=pools,
        faction_profile_targets=[],
    )
    ids = {row.faction_id for row in candidates}
    assert "faction-horde-forsaken" not in ids
    assert "faction-forsaken" in ids
    assert "faction-horde" in ids


def test_seed_mention_harvest_ignores_unlinked_prose_phrases() -> None:
    # No open-vocabulary phrase matching: prose naming a faction without a link (and with
    # no stored target establishing it) discovers nothing.
    candidates = collect_faction_candidates(
        zone_id="zone-example",
        evidence_rows=[],
        pools={
            "faction_pool": [],
            "faction_role_pool": [
                _seed_item("The Argent Crusade presses its campaign across the land.")
            ],
        },
        faction_profile_targets=[],
    )
    assert candidates == []


def test_seed_mention_harvest_discovers_org_unknown_to_deleted_vocab() -> None:
    # A faction whose name shares no token with the deleted vocabulary ("Kirin Tor" —
    # the "Defias Brotherhood"-shaped case) is discovered purely via its link target
    # being a registry organization.
    candidates = collect_faction_candidates(
        zone_id="zone-example",
        evidence_rows=[],
        pools={
            "faction_pool": [],
            "faction_role_pool": [
                _seed_item(
                    "The Kirin Tor maintain a presence in Example Zone.",
                    links=[_link("Kirin Tor")],
                )
            ],
        },
        faction_profile_targets=[],
    )
    assert [row.faction_id for row in candidates] == ["faction-kirin-tor"]
    assert candidates[0].name == "Kirin Tor"
