from __future__ import annotations

import hashlib

from pipeline.generate.draft.claim_routing import (
    ACTIVE_MECHANICS_STATE,
    ACTIVE_OUTCOME,
    SAFE_ENTRY_CONTEXT,
    apply_claim_views_to_evidence_rows,
    build_claim_view_routing_decisions,
    route_claim_views_for_pool,
)
from pipeline.generate.draft.pages.assembly import (
    _build_evidence_pools,
    _build_instance_evidence_pools,
    _pointer_for_item,
)
from pipeline.generate.draft.pages.key_characters import _key_character_summary_pool
from pipeline.generate.draft.temporal import (
    ACTIVE_STORYLINE_OUTCOME,
    ENTRY_STATE,
    HISTORY_EXCLUDED_OUTCOME,
    HISTORY_NOT_APPLICABLE,
    HISTORY_SETUP_BRIDGE,
    POST_ACTIVE_LORE,
)


def _row(field_name: str, canonical_id: str, snippet: str, *, source_id: str = "src-zone") -> dict:
    return {
        "subject_id": "zone-example",
        "subject_type": "zone",
        "field_name": field_name,
        "build_meta": {"run_id": "test", "source_id": source_id},
        "evidence_items": [
            {
                "source_url": "https://example.test/wiki/Zone",
                "source_title": "Zone",
                "snippet": snippet,
                "section_role": "history",
                "raw_section_role": "history",
                "canonical_evidence_id": canonical_id,
            }
        ],
    }


def _claim_decision(canonical_id: str, source_excerpt: str, claims: list[dict]) -> dict:
    return {
        "canonical_evidence_id": canonical_id,
        "source_id": "src-zone",
        "source_title": "Zone",
        "source_excerpt": source_excerpt,
        "claims": [
            {
                "canonical_evidence_id": canonical_id,
                "source_excerpt": source_excerpt,
                **claim,
            }
            for claim in claims
        ],
    }


def test_safe_claim_from_mixed_paragraph_routes_without_outcome_sibling() -> None:
    source_excerpt = (
        "The Cenarion Circle begins healing the fields, while the battle later ends "
        "with one faction claiming Andorhal."
    )
    rows = [
        _row("history_digest", "canonical-mixed", source_excerpt),
        _row("currently_input", "canonical-mixed", source_excerpt),
        _row("at_a_glance_input", "canonical-mixed", source_excerpt),
    ]
    routed_rows = apply_claim_views_to_evidence_rows(
        rows,
        [
            _claim_decision(
                "canonical-mixed",
                source_excerpt,
                [
                    {
                        "claim_id": "claim-setup",
                        "claim_text": "The Cenarion Circle begins healing the fields.",
                        "claim_type": "faction_presence",
                        "temporal_scope": ENTRY_STATE,
                        "history_eligibility": HISTORY_SETUP_BRIDGE,
                        "spoiler_safety": SAFE_ENTRY_CONTEXT,
                    },
                    {
                        "claim_id": "claim-outcome",
                        "claim_text": "One faction claims Andorhal.",
                        "claim_type": "event",
                        "temporal_scope": ACTIVE_STORYLINE_OUTCOME,
                        "history_eligibility": HISTORY_EXCLUDED_OUTCOME,
                        "spoiler_safety": ACTIVE_OUTCOME,
                    },
                ],
            )
        ],
    )

    pools = _build_evidence_pools(routed_rows)

    assert [item["snippet"] for item in pools["history_pool"]] == [
        "The Cenarion Circle begins healing the fields."
    ]
    assert [item["snippet"] for item in pools["currently_pool"]] == [
        "The Cenarion Circle begins healing the fields."
    ]
    assert [item["snippet"] for item in pools["at_a_glance_pool"]] == [
        "The Cenarion Circle begins healing the fields."
    ]
    assert all("Andorhal" not in item["snippet"] for pool in pools.values() for item in pool)
    assert pools["history_pool"][0]["source_excerpt"] == source_excerpt
    pointer = _pointer_for_item(pools["history_pool"][0], {"src-zone": "mw:1"}, 1)
    assert pointer is not None
    assert "claim_id" not in pointer
    expected_hash = hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest()[:16]
    assert pointer["excerpt_hash"] == f"sha256:{expected_hash}"


def test_location_route_excludes_post_active_claim() -> None:
    """Slice 10 task 1: a location's post-active claim is stripped from the routed location pool."""
    source_excerpt = (
        "Strahnbrad lies to the north, and the Fourth War later swept through the ruined town."
    )
    rows = [_row("location_pool", "canonical-loc", source_excerpt)]
    routed_rows = apply_claim_views_to_evidence_rows(
        rows,
        [
            _claim_decision(
                "canonical-loc",
                source_excerpt,
                [
                    {
                        "claim_id": "loc-safe",
                        "claim_text": "Strahnbrad lies to the north.",
                        "claim_type": "location_status",
                        "temporal_scope": ENTRY_STATE,
                        "history_eligibility": HISTORY_NOT_APPLICABLE,
                        "spoiler_safety": SAFE_ENTRY_CONTEXT,
                    },
                    {
                        "claim_id": "loc-post",
                        "claim_text": "The Fourth War later swept through Strahnbrad.",
                        "claim_type": "event",
                        "temporal_scope": POST_ACTIVE_LORE,
                        "history_eligibility": HISTORY_EXCLUDED_OUTCOME,
                        "spoiler_safety": "post_active_reference",
                    },
                ],
            )
        ],
    )

    pools = _build_evidence_pools(routed_rows)
    snippets = [item["snippet"] for item in pools["location_pool"]]

    assert "Strahnbrad lies to the north." in snippets
    assert all("Fourth War" not in snippet for snippet in snippets)


def test_paragraph_pool_fallback_remains_when_claim_views_are_absent() -> None:
    rows = [
        _row(
            "history_digest",
            "canonical-background",
            "The old road was fortified before the current fighting began.",
        )
    ]

    pools = _build_evidence_pools(rows)

    assert [item["snippet"] for item in pools["history_pool"]] == [
        "The old road was fortified before the current fighting began."
    ]


def test_key_character_claim_route_excludes_mechanics_state() -> None:
    source_excerpt = "Course: Reeducation appears as an encounter state in the academy."
    rows = [
        {
            **_row("boss_pool", "canonical-course", source_excerpt),
            "subject_id": "instance-example",
            "subject_type": "instance",
        }
    ]
    routed_rows = apply_claim_views_to_evidence_rows(
        rows,
        [
            _claim_decision(
                "canonical-course",
                source_excerpt,
                [
                    {
                        "claim_id": "claim-course-mechanics",
                        "claim_text": source_excerpt,
                        "claim_type": "encounter_state",
                        "temporal_scope": ENTRY_STATE,
                        "history_eligibility": HISTORY_NOT_APPLICABLE,
                        "spoiler_safety": ACTIVE_MECHANICS_STATE,
                    }
                ],
            )
        ],
    )
    pools = _build_instance_evidence_pools(routed_rows, instance_name="Example")

    assert pools["boss_pool"]
    assert _key_character_summary_pool(pools["boss_pool"]) == []


def test_claim_view_routing_sidecar_counts_routeable_claims() -> None:
    source_excerpt = "The Cenarion Circle begins healing the fields."
    routed_rows = apply_claim_views_to_evidence_rows(
        [_row("history_digest", "canonical-setup", source_excerpt)],
        [
            _claim_decision(
                "canonical-setup",
                source_excerpt,
                [
                    {
                        "claim_id": "claim-setup",
                        "claim_text": source_excerpt,
                        "claim_type": "faction_presence",
                        "temporal_scope": ENTRY_STATE,
                        "history_eligibility": HISTORY_SETUP_BRIDGE,
                        "spoiler_safety": SAFE_ENTRY_CONTEXT,
                    }
                ],
            )
        ],
    )

    decisions = build_claim_view_routing_decisions(routed_rows)

    assert decisions[0]["route_counts"]["history"] == 1
    assert decisions[0]["route_counts"]["key_character"] == 1
    assert decisions[0]["routeable_claim_ids"]["history"] == ["claim-setup"]


def test_route_claim_views_for_pool_returns_paragraphs_without_sidecar() -> None:
    paragraph_pool = [{"snippet": "A paragraph-only evidence item."}]

    assert route_claim_views_for_pool(paragraph_pool, "history") == paragraph_pool


def test_prefer_entry_state_first_promotes_entry_state_claims() -> None:
    from pipeline.generate.draft.claim_routing import prefer_entry_state_first

    pool = [
        {"snippet": "old origin", "temporal_scope": "pre_entry_history", "is_claim_view": True},
        {"snippet": "current state", "temporal_scope": "entry_state", "is_claim_view": True},
        {"snippet": "active fight", "temporal_scope": "active_storyline", "is_claim_view": True},
    ]

    ordered = prefer_entry_state_first(pool)

    assert [item["snippet"] for item in ordered] == ["current state", "active fight", "old origin"]


def test_prefer_entry_state_first_tiebreaks_on_safe_entry_context() -> None:
    from pipeline.generate.draft.claim_routing import prefer_entry_state_first

    pool = [
        {
            "snippet": "background identity",
            "temporal_scope": "entry_state",
            "spoiler_safety": "safe_background",
            "is_claim_view": True,
        },
        {
            "snippet": "entry context",
            "temporal_scope": "entry_state",
            "spoiler_safety": "safe_entry_context",
            "is_claim_view": True,
        },
    ]

    ordered = prefer_entry_state_first(pool)

    assert [item["snippet"] for item in ordered] == ["entry context", "background identity"]


def test_prefer_entry_state_first_is_noop_without_claim_views() -> None:
    from pipeline.generate.draft.claim_routing import prefer_entry_state_first

    paragraph_pool = [
        {"snippet": "first paragraph", "temporal_scope": "pre_entry_history"},
        {"snippet": "second paragraph", "temporal_scope": "entry_state"},
    ]

    # Identity preserved (same object) so offline paragraph pools are byte-identical.
    assert prefer_entry_state_first(paragraph_pool) is paragraph_pool


def test_prefer_entry_state_first_mixed_pool_keeps_paragraphs_neutral() -> None:
    """A live routed pool mixes claim views and paragraphs; paragraphs hold a neutral mid rank.

    Entry-state claims are promoted ahead of paragraphs, pre-entry-history claims fall behind them,
    and the paragraph item is NOT reordered by its coarse paragraph-level temporal_scope.
    """
    from pipeline.generate.draft.claim_routing import prefer_entry_state_first

    pool = [
        {"snippet": "old origin claim", "temporal_scope": "pre_entry_history", "is_claim_view": True},
        # Paragraph item carries a paragraph-level entry_state label, but no claim view.
        {"snippet": "paragraph", "temporal_scope": "entry_state"},
        {"snippet": "entry claim", "temporal_scope": "entry_state", "is_claim_view": True},
    ]

    ordered = prefer_entry_state_first(pool)

    # entry-state claim first; paragraph stays neutral (mid); old-origin claim last.
    assert [item["snippet"] for item in ordered] == [
        "entry claim",
        "paragraph",
        "old origin claim",
    ]
