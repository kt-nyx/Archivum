from __future__ import annotations

import hashlib

from pipeline.common.linguistics import sentence_spans
from pipeline.generate.draft.claim_routing import (
    ACTIVE_MECHANICS_STATE,
    ACTIVE_OUTCOME,
    CLAIM_VIEW_KEY,
    KEY_CHARACTER_ROUTE,
    SAFE_ENTRY_CONTEXT,
    apply_claim_views_to_evidence_rows,
    build_claim_view_routing_decisions,
    reconstruct_safe_paragraph_excerpts,
    route_claim_views_for_pool,
    safe_intent_excerpt,
    safe_paragraph_excerpt,
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


def _kc_view(
    text: str,
    claim_type: str,
    *,
    entities: list[dict] | None = None,
    section_role: str = "",
    content_role: str = "",
) -> dict:
    return {
        "snippet": text,
        "claim_text": text,
        "claim_type": claim_type,
        "entities": entities or [],
        "section_role": section_role,
        "raw_section_role": section_role,
        "content_role": content_role,
        "is_claim_view": True,
    }


def test_order_key_character_views_follows_chronological_spine() -> None:
    """The biography is ordered chronologically (Fix 3): origin first, then expansion sections in
    release order, so the arrival that explains the figure's presence lands last instead of leading.

    Mirrors the Lilian Voss regression, where the summary opened on the in-instance moment and
    back-filled. With per-expansion section tags the arc now reads in order:
    life -> cataclysm -> mists (turn toward Scholomance).
    """
    from pipeline.generate.draft.pages.key_characters import _order_key_character_summary_views

    views = [
        _kc_view(
            "Voss redirects her attention to the necromancers within Scholomance.",
            "state",
            section_role="mists_of_pandaria_edit",
            entities=[{"name": "Scholomance"}],
        ),
        _kc_view("Voss was killed prior to the Cataclysm.", "event", section_role="cataclysm_edit"),
        _kc_view(
            "Voss was raised by her father to be a weapon against the undead.",
            "identity",
            section_role="life_edit",
        ),
        _kc_view(
            "Voss began a campaign against the Crusade.",
            "objective",
            section_role="cataclysm_edit",
        ),
    ]

    ordered = _order_key_character_summary_views(views, instance_name="Scholomance")
    texts = [view["claim_text"] for view in ordered]

    # Origin (life) precedes Cataclysm precedes the Mists-era turn toward Scholomance.
    assert texts[0] == "Voss was raised by her father to be a weapon against the undead."
    assert texts[-1] == "Voss redirects her attention to the necromancers within Scholomance."
    assert texts.index("Voss began a campaign against the Crusade.") < texts.index(
        "Voss redirects her attention to the necromancers within Scholomance."
    )


def test_order_key_character_views_demotes_modern_lead() -> None:
    """Fix 2: once real non-lead biography exists, the whole-page lead is pushed to the back so it
    loses the evidence cap; if the lead is all the figure has, it is left in place."""
    from pipeline.generate.draft.pages.key_characters import _order_key_character_summary_views

    with_biography = [
        _kc_view(
            "Voss is a member of the Desolate Council and the Horde Council.",
            "identity",
            content_role="lead",
            section_role="lead",
        ),
        _kc_view(
            "Voss was raised to be a weapon against the undead.",
            "identity",
            section_role="life_edit",
        ),
    ]
    ordered = _order_key_character_summary_views(with_biography, instance_name="Scholomance")
    assert ordered[-1]["content_role"] == "lead"

    lead_only = [
        _kc_view("Rattlegore is a bone golem bound to the school.", "identity", content_role="lead"),
    ]
    kept = _order_key_character_summary_views(lead_only, instance_name="Scholomance")
    assert len(kept) == 1


def test_select_salient_views_guarantees_instance_beat_and_era_spread() -> None:
    """The evidence cap must keep the instance-relevant beat and spread across eras, not fill on one
    era's micro-claims (the Lilian Voss salience regression)."""
    from pipeline.generate.draft.pages.key_characters import _select_salient_key_character_views

    views = [
        _kc_view("Voss was raised as a weapon.", "state", section_role="life_edit"),
        _kc_view("Voss studied stealth and sorcery.", "other", section_role="life_edit"),
        _kc_view("Voss knew Lieutenant Gebler.", "relationship", section_role="life_edit"),
        _kc_view("Voss trained relentlessly.", "other", section_role="life_edit"),
        _kc_view("Voss died and was raised undead.", "event", section_role="cataclysm_edit"),
        _kc_view("Voss killed her father.", "event", section_role="cataclysm_edit"),
        _kc_view(
            "Voss ventured to eradicate the Scourge remnant in Scholomance.",
            "objective",
            section_role="mists_of_pandaria_edit",
        ),
    ]

    selected = _select_salient_key_character_views(views, instance_name="Scholomance", limit=4)
    texts = [v["claim_text"] for v in selected]

    assert "Voss ventured to eradicate the Scourge remnant in Scholomance." in texts
    life_kept = sum(1 for v in selected if v["section_role"] == "life_edit")
    assert life_kept <= 2  # one era's micro-claims do not swamp the window
    assert any(v["section_role"] == "cataclysm_edit" for v in selected)
    assert len(selected) == 4


_RECON_PARAGRAPH = (
    "Alpha happened first. Beta is the spoiler outcome. Gamma is safe background."
)


def _recon_spans() -> list[list[int]]:
    # Real NLP segmentation (never a hand-typed offset table): views carry the same
    # character offsets claim extraction would have stored.
    return [[span.start, span.end] for span in sentence_spans(_RECON_PARAGRAPH)]


def _recon_claim(sentence_index: int, *, scope: str, safety: str, text: str) -> dict:
    return {
        "canonical_evidence_id": "c1",
        "source_excerpt": _RECON_PARAGRAPH,
        "source_sentence_indexes": [sentence_index],
        "source_char_spans": [_recon_spans()[sentence_index]],
        "temporal_scope": scope,
        "spoiler_safety": safety,
        "claim_text": text,
        "is_claim_view": True,
    }


def test_safe_paragraph_excerpt_keeps_safe_sentences_drops_spoiler() -> None:
    views = [
        _recon_claim(0, scope="pre_entry_history", safety="safe_background", text="Alpha"),
        _recon_claim(1, scope="active_storyline_outcome", safety="active_outcome", text="Beta"),
        _recon_claim(2, scope="pre_entry_history", safety="safe_background", text="Gamma"),
    ]
    excerpt = safe_paragraph_excerpt(views, KEY_CHARACTER_ROUTE, paragraph_text=_RECON_PARAGRAPH)
    assert "Alpha happened first." in excerpt
    assert "Gamma is safe background." in excerpt
    assert "Beta" not in excerpt  # the spoiler-outcome sentence is dropped


def test_safe_paragraph_excerpt_drops_contaminated_sentence() -> None:
    # Sentence 0 produced a safe claim AND a spoiler claim (LLM split): it is dropped whole so no
    # future/outcome content leaks back into the reconstructed prose.
    views = [
        _recon_claim(0, scope="pre_entry_history", safety="safe_background", text="Alpha-safe"),
        _recon_claim(0, scope="active_storyline_outcome", safety="active_outcome", text="Alpha-bad"),
        _recon_claim(2, scope="pre_entry_history", safety="safe_background", text="Gamma"),
    ]
    excerpt = safe_paragraph_excerpt(views, KEY_CHARACTER_ROUTE, paragraph_text=_RECON_PARAGRAPH)
    assert "Alpha" not in excerpt
    assert "Gamma is safe background." in excerpt


def test_safe_paragraph_excerpt_requires_offsets() -> None:
    # A view without stored character offsets makes the contaminated set unknowable: the
    # reconstruction refuses (callers fall back to claim-text fragments) rather than guessing
    # by re-splitting and substring-matching.
    view = _recon_claim(0, scope="pre_entry_history", safety="safe_background", text="Alpha")
    del view["source_char_spans"]
    assert (
        safe_paragraph_excerpt([view], KEY_CHARACTER_ROUTE, paragraph_text=_RECON_PARAGRAPH) == ""
    )


def test_reconstruct_safe_paragraph_excerpts_maps_by_canonical_id() -> None:
    item = {
        "snippet": _RECON_PARAGRAPH,
        CLAIM_VIEW_KEY: [
            _recon_claim(0, scope="pre_entry_history", safety="safe_background", text="Alpha"),
            _recon_claim(1, scope="active_storyline_outcome", safety="active_outcome", text="Beta"),
        ],
    }
    excerpts = reconstruct_safe_paragraph_excerpts([item], KEY_CHARACTER_ROUTE)
    assert set(excerpts) == {"c1"}
    assert "Alpha happened first." in excerpts["c1"]
    assert "Beta" not in excerpts["c1"]


def test_select_salient_views_noop_within_cap() -> None:
    from pipeline.generate.draft.pages.key_characters import _select_salient_key_character_views

    views = [_kc_view("only claim", "state", section_role="life_edit")]
    assert _select_salient_key_character_views(views, instance_name="Scholomance", limit=14) == views


def test_order_key_character_views_is_stable_and_paragraph_safe() -> None:
    """Paragraph fallback items (no claim_type) keep their original relative order."""
    from pipeline.generate.draft.pages.key_characters import _order_key_character_summary_views

    views = [
        {"snippet": "first paragraph", "claim_text": "first paragraph"},
        {"snippet": "second paragraph", "claim_text": "second paragraph"},
    ]

    ordered = _order_key_character_summary_views(views, instance_name="Scholomance")

    assert [view["snippet"] for view in ordered] == ["first paragraph", "second paragraph"]


def test_claim_views_carry_source_char_spans() -> None:
    """Slice 8: stored character offsets survive the claim -> view translation so excerpt
    reconstruction never re-splits and substring-matches."""
    paragraph = "The Cenarion Circle begins healing the fields."
    span = sentence_spans(paragraph)[0]
    routed_rows = apply_claim_views_to_evidence_rows(
        [_row("history_digest", "canonical-spans", paragraph)],
        [
            _claim_decision(
                "canonical-spans",
                paragraph,
                [
                    {
                        "claim_id": "claim-spans",
                        "claim_text": paragraph,
                        "claim_type": "state",
                        "temporal_scope": ENTRY_STATE,
                        "history_eligibility": HISTORY_SETUP_BRIDGE,
                        "spoiler_safety": SAFE_ENTRY_CONTEXT,
                        "source_sentence_indexes": [0],
                        "source_char_spans": [[span.start, span.end]],
                    }
                ],
            )
        ],
    )
    view = routed_rows[0]["evidence_items"][0][CLAIM_VIEW_KEY][0]
    assert view["source_char_spans"] == [[span.start, span.end]]


def test_safe_intent_excerpt_keeps_aim_drops_outcome() -> None:
    # Cause 3: a spoiler-shaped hook sentence yields its spoiler-safe intent clause; the
    # reversal/outcome tail after the adversative connective is dropped.
    view = {
        "claim_text": (
            "She redirected her attention to the necromancers within Scholomance and intended "
            "to kill Darkmaster Gandling, though it failed as he turned her against the adventurer."
        )
    }
    intent = safe_intent_excerpt(view)
    assert "Scholomance" in intent
    assert "intended to kill" in intent
    assert "failed" not in intent
    assert "adventurer" not in intent


def test_safe_intent_excerpt_empty_without_outcome_tail() -> None:
    # A single realis assertion with no adversative tail stays filtered (returns "") so no
    # outcome ever leaks back in.
    assert safe_intent_excerpt({"claim_text": "She defeated Gandling in the Chamber of Summoning."}) == ""
