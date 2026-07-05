from __future__ import annotations

from typing import Any

from pipeline.generate.draft.faction_scoring import (
    collect_faction_candidates,
    harvest_instance_anchor_tokens,
    harvest_instance_faction_targets,
    score_faction_candidate,
)


def _row(*snippets: str, field_name: str = "history_digest", section_role: str = "history") -> dict[str, Any]:
    return {
        "field_name": field_name,
        "section_role": section_role,
        "evidence_items": [
            {"source_id": f"src-{i}", "snippet": s, "section_role": section_role}
            for i, s in enumerate(snippets)
        ],
    }


def test_harvest_extracts_multiword_faction_with_double_connector() -> None:
    rows = [
        _row("The Cult of the Damned seized Scholomance." * 1),
        _row("The Cult of the Damned raised the dead at Scholomance."),
        _row("Members of the Cult of the Damned still haunt Scholomance."),
    ]
    targets, _ = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    names = {t["name"] for t in targets}
    assert "Cult of the Damned" in names
    assert any(t["faction_id"] == "faction-cult-of-the-damned" for t in targets)


def test_harvest_keeps_standalone_faction_drops_generic_single_word() -> None:
    rows = [
        _row("The Scourge overran the keep."),
        _row("The Scourge claimed Scholomance."),
        _row("The Scourge remains."),
        # "Cult" appearing alone (no qualifier) is too generic to be a faction on its own.
        _row("A small Cult gathered.", "Another Cult met.", "A third Cult formed."),
        _row("Acolytes of the Cult learned in the school."),
    ]
    targets, _ = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    names = {t["name"] for t in targets}
    assert "Scourge" in names
    assert "Cult" not in names
    assert "Acolytes of the Cult" not in names


def test_harvest_does_not_merge_two_factions_joined_by_and() -> None:
    rows = [
        _row("The Argent Crusade and the Scourge clashed."),
        _row("The Argent Crusade and the Scourge clashed again."),
        _row("The Argent Crusade and the Scourge clashed once more."),
    ]
    targets, _ = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    names = {t["name"] for t in targets}
    assert "Scourge" in names
    assert "Argent Crusade" in names
    assert not any("and" in n.lower() for n in names)


def test_harvest_min_mentions_threshold_filters_thin_factions() -> None:
    rows = [
        _row("The Scourge struck.", "The Scourge struck.", "The Scourge struck."),
        _row("The Forsaken appeared once."),  # only one mention -> below default threshold
    ]
    targets, _ = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    names = {t["name"] for t in targets}
    assert "Scourge" in names
    assert "Forsaken" not in names


def test_harvest_excludes_instance_name_itself() -> None:
    rows = [_row("Scholomance Scholomance Scholomance is a school of necromancy.")]
    targets, _ = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    assert all(t["name"].lower() != "scholomance" for t in targets)


def test_harvested_factions_feed_scorer_and_rank_by_evidence() -> None:
    rows = [
        _row(f"The Scourge held Scholomance ({i}).") for i in range(5)
    ] + [
        _row(f"The Cult of the Damned served at Scholomance ({i}).") for i in range(3)
    ]
    targets, pool = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    cands = collect_faction_candidates(
        zone_id="instance-scholomance",
        evidence_rows=rows,
        pools={"faction_role_pool": pool, "faction_pool": []},
        faction_profile_targets=targets,
    )
    scored = {c.name: score_faction_candidate(c, zone_name="Scholomance").score for c in cands}
    assert scored["Scourge"] > scored["Cult of the Damned"] > 0


def test_harvest_reads_source_id_from_pack_build_meta() -> None:
    # Real evidence items carry no item-level ``source_id`` — it lives on the pack's
    # ``build_meta``. Reading it from the item left every role-pool row with ``source_id=""``,
    # so faction provenance pointers could not resolve and the instance gate hard-failed.
    rows = [
        {
            "field_name": "history_digest",
            "section_role": "history",
            "build_meta": {"source_id": "src-scholomance-overview"},
            "evidence_items": [
                {
                    "snippet": "The Scourge raised the dead beneath Scholomance.",
                    "content_role": "lore_history",
                    "raw_section_role": "history_edit",
                }
            ],
        }
    ]
    _, pool = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )
    assert pool
    assert all(item["source_id"] == "src-scholomance-overview" for item in pool)
    # The role/content fields ride along so pointer locators stay accurate.
    assert pool[0]["content_role"] == "lore_history"


def test_harvest_skips_temporally_excluded_instance_evidence() -> None:
    rows = [
        _row(
            "The Shadow Council bargained with the Cult of the Damned.",
            "The Shadow Council sought a book from the Cult of the Damned.",
            "The Shadow Council made common cause with the Cult of the Damned.",
        )
    ]
    for item in rows[0]["evidence_items"]:
        item["temporal_scope"] = "post_active_lore"

    targets, pool = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )

    assert targets == []
    assert pool == []


def test_harvest_ignores_biography_only_mentions_for_instance_factions() -> None:
    rows = [
        _row(
            "The Scourge raised the dead beneath Scholomance.",
            "The Scourge defended the academy's halls.",
            "The Scourge still occupies the ruined school.",
            field_name="history_digest",
            section_role="history",
        ),
        _row(
            "Lilian Voss was trained by the Scarlet Crusade.",
            "The Scarlet Crusade hunted Lilian Voss after her undeath.",
            "Scarlet Crusade zealots shaped Lilian Voss's early biography.",
            field_name="character_pool",
            section_role="character_biography",
        ),
    ]

    targets, pool = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )

    names = {target["name"] for target in targets}
    assert "Scourge" in names
    assert "Scarlet Crusade" not in names
    assert all("Scarlet Crusade" not in item["snippet"] for item in pool)


def test_harvest_allows_multiword_faction_with_eligible_history_support() -> None:
    rows = [
        _row(
            "The Cult of the Damned founded the school beneath the island.",
            "The Cult of the Damned still trains necromancers in the current holdout.",
        ),
        _row(
            "The Shadow Council later entered the school.",
            "The Shadow Council later searched the school.",
            "The Shadow Council later departed the school.",
        ),
    ]
    for item in rows[0]["evidence_items"]:
        item["temporal_scope"] = "entry_state"
        item["history_eligibility"] = "history_setup_bridge"
    for item in rows[1]["evidence_items"]:
        item["temporal_scope"] = "post_active_lore"
        item["history_eligibility"] = "history_excluded_post_active"

    targets, pool = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
    )

    names = {t["name"] for t in targets}
    assert "Cult of the Damned" in names
    assert "Shadow Council" not in names
    assert len(pool) == 2


def test_harvest_uses_eligible_structured_links_as_canonical_faction_support() -> None:
    rows = [
        {
            "field_name": "history_digest",
            "section_role": "history",
            "build_meta": {"source_id": "src-instance", "raw_section_role": "background_edit"},
            "evidence_items": [
                {
                    "snippet": "Acolytes of the Cult learned their craft beneath the island.",
                    "section_role": "background_edit",
                    "raw_section_role": "background_edit",
                    "temporal_scope": "pre_entry_history",
                    "history_eligibility": "history_background",
                }
            ],
        },
        {
            "field_name": "history_digest",
            "section_role": "history",
            "build_meta": {"source_id": "src-instance", "raw_section_role": "later_edit"},
            "evidence_items": [
                {
                    "snippet": "A later cabal asked the Cult for a forbidden book.",
                    "section_role": "later_edit",
                    "raw_section_role": "later_edit",
                    "temporal_scope": "post_active_lore",
                    "history_eligibility": "history_excluded_post_active",
                }
            ],
        },
    ]
    snapshots = [
        {
            "source_id": "src-instance",
            "structured_links": [
                {"label": "Cult of the Damned", "section_role": "background_edit"},
                {
                    "label": "Shadow Council",
                    "section_role": "later_edit",
                    "parent_section_role": "background_edit",
                },
            ],
        }
    ]

    targets, pool = harvest_instance_faction_targets(
        instance_id="instance-scholomance",
        instance_name="Scholomance",
        evidence_rows=rows,
        snapshots=snapshots,
    )

    names = {t["name"] for t in targets}
    assert "Cult of the Damned" in names
    assert "Shadow Council" not in names
    assert any("Cult of the Damned: Acolytes of the Cult" in item["snippet"] for item in pool)


def test_anchor_tokens_harvest_frequent_places_excluding_instance() -> None:
    rows = [
        _row("Caer Darrow held the Barov estate.") for _ in range(3)
    ] + [
        _row("Scholomance lies beneath Caer Darrow.") for _ in range(3)
    ]
    tokens = harvest_instance_anchor_tokens(rows, instance_name="Scholomance")
    lowered = {t.lower() for t in tokens}
    assert "caer darrow" in lowered  # frequent place -> usable as a summary anchor
    assert "scholomance" not in lowered  # the instance itself is never its own anchor
