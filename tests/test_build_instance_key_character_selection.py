from __future__ import annotations

from pipeline.discovery.instance_bosses import BossCandidate
from pipeline.generate.draft import prose_selection as workers
from pipeline.generate.draft.pages import (
    build_instance_key_character_selection,
    build_instance_page,
)
from pipeline.generate.draft.pages import key_characters as key_character_page


def test_merge_character_profile_evidence_prepends_biography_with_name_drift() -> None:
    # Slice D: crawled character-page biography is attached to each cast member's profile_pool,
    # tolerating page-title vs roster-name drift, and prepended ahead of structural mentions.
    cast = [
        BossCandidate(
            boss_id="boss-gandling",
            name="Darkmaster Gandling",
            wiki_url="",
            source_section_role="dungeon_journal",
        ),
        BossCandidate(
            boss_id="boss-voss",
            name="Lilian Voss",
            wiki_url="",
            source_section_role="dungeon_journal",
            profile_pool=[{"snippet": "structural mention", "source_id": "src-instance"}],
        ),
    ]
    character_pool = [
        {"snippet": "Gandling biography.", "character_name": "Gandling", "source_id": "src-g"},
        {"snippet": "Voss biography.", "character_name": "Lilian Voss", "source_id": "src-v"},
    ]
    key_character_page._merge_character_profile_evidence(cast, character_pool)

    # Exact name match, prepended ahead of the pre-existing structural mention.
    assert cast[1].profile_pool[0]["snippet"] == "Voss biography."
    assert any("structural mention" in str(i.get("snippet")) for i in cast[1].profile_pool)
    # Fuzzy: page "Gandling" binds to roster "Darkmaster Gandling".
    assert any("Gandling biography" in str(i.get("snippet")) for i in cast[0].profile_pool)


def test_merge_character_profile_evidence_noop_without_pool() -> None:
    cast = [
        BossCandidate(
            boss_id="boss-x",
            name="Someone",
            wiki_url="",
            source_section_role="dungeon_journal",
            profile_pool=[{"snippet": "kept", "source_id": "s"}],
        )
    ]
    key_character_page._merge_character_profile_evidence(cast, [])
    assert cast[0].profile_pool == [{"snippet": "kept", "source_id": "s"}]


def test_must_include_appears_when_llm_returns_empty(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        workers, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})()
    )
    monkeypatch.setattr(workers, "llm_json_with_retry", lambda **kwargs: {"selected": []})

    selection = build_instance_key_character_selection(
        instance_id="instance-test",
        instance_name="Test Keep",
        evidence_rows=[
            {
                "subject_id": "instance-test",
                "field_name": "boss_pool",
                "evidence_items": [
                    {
                        "snippet": "Journal lists /wiki/Must_Include_Boss as final encounter.",
                        "section_role": "dungeon_journal",
                    }
                ],
            }
        ],
        section_blocks=[],
        snapshots=[],
    )
    assert [row.name for row in selection.cast] == ["Must Include Boss"]
    assert selection.selection_reasons["Must Include Boss"] == "must_include_floor"


def test_structural_roster_is_not_padded_with_denizen_llm_picks(monkeypatch) -> None:
    # When the page yields a structural boss roster, that roster IS the cast: the LLM does not
    # pad it with denizen trash / narrative-only figures the gold cast excludes (e.g. Holmberg).
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    monkeypatch.setattr(
        workers, "load_ai_settings", lambda: type("S", (), {"openai_ready": True})()
    )
    monkeypatch.setattr(
        workers,
        "llm_json_with_retry",
        lambda **kwargs: {"selected": ["Story Figure"]},
    )

    selection = build_instance_key_character_selection(
        instance_id="instance-test",
        instance_name="Test Keep",
        evidence_rows=[
            {
                "subject_id": "instance-test",
                "field_name": "boss_pool",
                "evidence_items": [
                    {
                        "snippet": "/wiki/Floor_Boss",
                        "section_role": "dungeon_journal",
                    }
                ],
            },
            {
                "subject_id": "instance-test",
                "field_name": "at_a_glance_input",
                "evidence_items": [
                    {
                        "snippet": "Story Figure Story Figure anchors the Test Keep narrative.",
                        "section_role": "lead",
                    }
                ],
            },
        ],
        section_blocks=[
            {
                "section_role": "denizens",
                "text": '<a href="/wiki/Story_Figure">Story Figure</a>',
            }
        ],
        snapshots=[],
    )
    assert [row.name for row in selection.cast] == ["Floor Boss"]
    assert selection.selection_reasons["Floor Boss"] == "must_include_floor"
    assert "Story Figure" not in selection.selection_reasons


def test_finalize_emits_selection_reason_codes(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    build_meta = {"source_id": "src-instance", "source_kind": "seed"}
    draft = build_instance_page(
        {
            "entity_id": "instance-test",
            "entity_type": "instance",
            "name": "Test Keep",
            "parent_zone_id": "zone-test",
            "source_ids": ["src-instance"],
            "revision_ids": ["mw:1"],
            "source_urls": {"src-instance": "https://warcraft.wiki.gg/wiki/Test_Keep"},
        },
        [
            {
                "subject_id": "instance-test",
                "field_name": "boss_pool",
                "evidence_items": [
                    {
                        "snippet": "Floor Boss guards /wiki/Floor_Boss within the keep.",
                        "section_role": "dungeon_journal",
                    }
                ],
                "build_meta": build_meta,
            },
            {
                "subject_id": "instance-test",
                "field_name": "at_a_glance_input",
                "evidence_items": [
                    {
                        "snippet": "Test Keep is a blighted vault watched by Floor Boss.",
                        "section_role": "lead",
                    }
                ],
                "build_meta": build_meta,
            },
        ],
        {"lore_source": "instance_page"},
        section_blocks=[
            {
                "section_role": "denizens",
                "text": '<a href="/wiki/Story_Figure">Story Figure</a>',
            }
        ],
    )
    assert draft["key_characters"]
    codes = {
        code for card in draft["key_characters"] for code in card.get("decision_reason_codes", [])
    }
    assert "must_include_floor" in codes


def test_sidecar_rows_include_merge_rank() -> None:
    from pipeline.generate.draft_writer import _build_key_character_decision_row

    build_meta = {"source_id": "src-instance", "source_kind": "seed"}
    # Single-source contract: the sidecar reuses the selection the page emitted from,
    # so build it once here and feed it in (the writer does the same via selection_sink).
    selection = build_instance_key_character_selection(
        instance_id="instance-test",
        instance_name="Test Keep",
        evidence_rows=[
            {
                "subject_id": "instance-test",
                "field_name": "boss_pool",
                "evidence_items": [
                    {
                        "snippet": "/wiki/Floor_Boss",
                        "section_role": "dungeon_journal",
                    }
                ],
                "build_meta": build_meta,
            },
        ],
        section_blocks=[
            {
                "section_role": "denizens",
                "text": '<a href="/wiki/Story_Figure">Story Figure</a>',
            }
        ],
        snapshots=[],
    )
    row = _build_key_character_decision_row(
        instance_id="instance-test",
        instance_name="Test Keep",
        selection=selection,
        emitted_cards=[{"name": "Floor Boss"}],
    )
    candidates = row["candidates"]
    assert len(candidates) >= 2
    emitted = [item for item in candidates if item["emitted"]]
    assert emitted[0]["merge_rank"] == 1
    assert emitted[0]["selection_reason"] == "must_include_floor"
    assert "significance" not in emitted[0]
    non_emitted = [item for item in candidates if not item["emitted"]]
    assert all(item["merge_rank"] is None for item in non_emitted)
    # Single-source invariant: every emitted sidecar row carries a merge_rank, and the
    # emitted set equals the page-emitted cast (no emitted&&merge_rank==null divergence).
    assert all(item["merge_rank"] is not None for item in emitted)
    assert {item["name"] for item in emitted} == {"Floor Boss"}


def test_finalize_keeps_structural_role_when_summary_mentions_ally(monkeypatch) -> None:
    monkeypatch.setattr(
        key_character_page,
        "synthesize_key_character_summary",
        lambda pool, boss_name, instance_name, structural_role="": (
            "Lilian Voss is a brief, tragic ally who helps adventurers in Test Keep.",
            ["src-lilian"],
        ),
    )
    pool = [
        {
            "source_id": "src-lilian",
            "snippet": "Lilian Voss is a brief, tragic ally in Test Keep.",
            "section_role": "dungeon_journal",
        }
    ]
    cards, _, _ = key_character_page._finalize_key_characters(
        instance_name="Test Keep",
        boss_candidates=[
            BossCandidate(
                boss_id="character-lilian-voss",
                name="Lilian Voss",
                wiki_url="https://warcraft.wiki.gg/wiki/Lilian_Voss",
                source_section_role="dungeon_journal",
                profile_pool=pool,
                role="enemy",
                role_reason="enemy_section",
            )
        ],
        boss_pool=pool,
        revision_map={"src-lilian": "mw:1"},
        selection_reasons={"Lilian Voss": "must_include_floor"},
    )

    assert cards
    assert cards[0]["role"] == "enemy"
    assert "role:ally:summary_ally_descriptor" not in cards[0]["decision_reason_codes"]


def _claim_view(
    *,
    snippet: str,
    source_id: str,
    claim_id: str,
    spoiler_safety: str,
    temporal_scope: str = "entry_state",
) -> dict:
    return {
        "snippet": snippet,
        "claim_text": snippet,
        "source_excerpt": snippet,
        "source_id": source_id,
        "claim_id": claim_id,
        "canonical_evidence_id": f"canonical-{claim_id}",
        "field_name": "boss_pool",
        "temporal_scope": temporal_scope,
        "spoiler_safety": spoiler_safety,
        "is_claim_view": True,
    }


def _boss_pool_item_with_claims(views: list[dict]) -> dict:
    return {
        "source_id": "src-roster",
        "snippet": "Roster paragraph naming the academy faculty.",
        "section_role": "dungeon_journal",
        "_claim_views": views,
    }


def _gandling_candidate(pool: list[dict]) -> BossCandidate:
    return BossCandidate(
        boss_id="character-darkmaster-gandling",
        name="Darkmaster Gandling",
        wiki_url="https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
        source_section_role="dungeon_journal",
        profile_pool=pool,
        role="enemy",
        role_reason="enemy_section",
    )


def test_finalize_excludes_unsafe_claims_and_passes_avoid_hints(monkeypatch) -> None:
    """Slice 9: mechanics/outcome claims never reach prose, only the avoid-hints (clarification 1)."""
    captured: dict = {}

    def _synth(pool, *, boss_name, instance_name, structural_role="", **kwargs):
        captured["pool_snippets"] = [row.get("snippet") for row in pool]
        captured["avoid_hints"] = kwargs.get("avoid_hints")
        return (
            "Darkmaster Gandling is the stern headmaster who commands Scholomance's hostile faculty.",
            ["src-roster"],
        )

    monkeypatch.setattr(key_character_page, "synthesize_key_character_summary", _synth)

    pool = [
        _boss_pool_item_with_claims(
            [
                _claim_view(
                    snippet="Darkmaster Gandling commands the academy faculty.",
                    source_id="src-roster",
                    claim_id="claim-safe",
                    spoiler_safety="safe_entry_context",
                ),
                _claim_view(
                    snippet="Lilian Voss is defeated in the upper study.",
                    source_id="src-roster",
                    claim_id="claim-unsafe",
                    spoiler_safety="active_mechanics_state",
                ),
            ]
        )
    ]
    cards, _prov, _used = key_character_page._finalize_key_characters(
        instance_name="Scholomance",
        boss_candidates=[_gandling_candidate(pool)],
        boss_pool=pool,
        revision_map={"src-roster": "mw:1"},
        selection_reasons={"Darkmaster Gandling": "must_include_floor"},
    )

    assert cards
    # Only the safe claim text reached the summary pool; the mechanics claim was excluded.
    assert captured["pool_snippets"] == ["Darkmaster Gandling commands the academy faculty."]
    # The mechanics claim is surfaced solely as an avoid-hint.
    assert captured["avoid_hints"] == ["Lilian Voss is defeated in the upper study."]
    codes = cards[0]["decision_reason_codes"]
    assert "summary_evidence:safe=1:unsafe=1" in codes
    assert "summary_source:structural_presence" not in codes


def test_finalize_uses_structural_fallback_when_only_unsafe_claims(monkeypatch) -> None:
    """Slice 9: with only spoiler-unsafe evidence, fall back to a restrained structural summary."""
    captured: dict = {}

    def _synth(pool, *, boss_name, instance_name, structural_role="", **kwargs):
        captured["pool_snippets"] = [row.get("snippet") for row in pool]
        return (
            "Darkmaster Gandling presides over Scholomance as one of its central adversaries.",
            ["src-roster"],
        )

    monkeypatch.setattr(key_character_page, "synthesize_key_character_summary", _synth)

    pool = [
        _boss_pool_item_with_claims(
            [
                _claim_view(
                    snippet="Lilian Voss is defeated in the upper study.",
                    source_id="src-roster",
                    claim_id="claim-unsafe",
                    spoiler_safety="active_mechanics_state",
                )
            ]
        )
    ]
    cards, _prov, _used = key_character_page._finalize_key_characters(
        instance_name="Scholomance",
        boss_candidates=[_gandling_candidate(pool)],
        boss_pool=pool,
        revision_map={"src-roster": "mw:1"},
        selection_reasons={"Darkmaster Gandling": "must_include_floor"},
    )

    assert cards
    # The unsafe mechanics snippet never seeded the summary; a neutral structural snippet did.
    assert "defeated" not in " ".join(captured["pool_snippets"]).lower()
    codes = cards[0]["decision_reason_codes"]
    assert "summary_source:structural_presence" in codes
    assert "summary_evidence:safe=0:unsafe=1" in codes


def test_finalize_paragraph_fallback_unchanged_without_claim_views(monkeypatch) -> None:
    """No claim views (offline/paragraph path): no avoid-hints, no structural fallback, unsafe=0."""
    captured: dict = {}

    def _synth(pool, *, boss_name, instance_name, structural_role="", **kwargs):
        captured["avoid_hints"] = kwargs.get("avoid_hints")
        return (
            "Darkmaster Gandling is the stern headmaster who commands Scholomance's hostile faculty.",
            ["src-roster"],
        )

    monkeypatch.setattr(key_character_page, "synthesize_key_character_summary", _synth)

    pool = [
        {
            "source_id": "src-roster",
            "snippet": "Darkmaster Gandling rules the academy and its faculty of necromancers.",
            "section_role": "dungeon_journal",
        }
    ]
    cards, _prov, _used = key_character_page._finalize_key_characters(
        instance_name="Scholomance",
        boss_candidates=[_gandling_candidate(pool)],
        boss_pool=pool,
        revision_map={"src-roster": "mw:1"},
        selection_reasons={"Darkmaster Gandling": "must_include_floor"},
    )

    assert cards
    assert captured["avoid_hints"] is None  # not passed when there are no unsafe claims
    codes = cards[0]["decision_reason_codes"]
    # Honest audit: no claim-level safety was assessed on the paragraph path.
    assert "summary_evidence:paragraph_fallback" in codes
    assert not any(code.startswith("summary_evidence:safe=") for code in codes)
    assert "summary_source:structural_presence" not in codes
