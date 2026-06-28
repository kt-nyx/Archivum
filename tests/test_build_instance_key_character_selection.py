from __future__ import annotations

from pipeline.discovery.instance_bosses import BossCandidate
from pipeline.generate.draft import prose_selection as workers
from pipeline.generate.draft.pages import (
    build_instance_key_character_selection,
    build_instance_page,
)
from pipeline.generate.draft.pages import key_characters as key_character_page


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
