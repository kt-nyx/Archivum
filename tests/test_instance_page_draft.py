from __future__ import annotations

import os
from pathlib import Path

from pipeline.generate.draft.instance_lint import lint_overview
from pipeline.generate.draft.prose_lint import word_count
from pipeline.generate.draft.wiki_first import _finalize_key_enemies, build_instance_page
from pipeline.discovery.instance_bosses import BossCandidate

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "instance"


def _long_history_snippet(instance_name: str) -> str:
    return (
        f"{instance_name} was founded as a school for battle-mages who studied forbidden necromancy "
        "after the kingdom fell to plague and civil war. Its founders claimed they could control "
        "death itself, training students in rituals that bound spirits to stone halls and shadowed "
        "lecture chambers beneath the blighted countryside. Over decades the institution became a "
        "stronghold for hostile instructors, rival cabals, and experiments that threatened every "
        "nearby settlement. Crusader patrols, adventurers, and local militias repeatedly assaulted "
        "the academy yet its inner vaults endured, guarded by fanatical wardens and archivists who "
        "preserved grim curricula. Each campaign left deeper scars across the region while survivors "
        "warned that the institution's leaders still coordinate recruitment, battlefield reinforcement, "
        "and ritual escalation beyond its crumbling gates."
    )


def _instance_evidence(instance_id: str, instance_name: str) -> list[dict[str, object]]:
    history = _long_history_snippet(instance_name)
    return [
        {
            "subject_id": instance_id,
            "subject_type": "instance",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": (
                        f"{instance_name} is a blighted academy where necromancers and hostile instructors "
                        "still train recruits beneath haunted lecture halls."
                    ),
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-instance", "source_kind": "seed"},
        },
        {
            "subject_id": instance_id,
            "subject_type": "instance",
            "field_name": "history_digest",
            "evidence_items": [{"snippet": history, "section_role": "history"}],
            "build_meta": {"source_id": "src-instance", "source_kind": "seed"},
        },
        {
            "subject_id": instance_id,
            "subject_type": "instance",
            "field_name": "boss_pool",
            "evidence_items": [
                {
                    "snippet": (
                        "Bosses include /wiki/Archivist_Maelor and /wiki/Warden_Voss who guard the inner vault."
                    ),
                    "section_role": "adventurers",
                }
            ],
            "build_meta": {"source_id": "src-instance", "source_kind": "seed"},
        },
    ]


def _fact_pack(instance_id: str, instance_name: str) -> dict[str, object]:
    return {
        "entity_id": instance_id,
        "entity_type": "instance",
        "name": instance_name,
        "parent_zone_id": "zone-example",
        "source_ids": ["src-instance"],
        "revision_ids": ["mw:100"],
        "source_urls": {"src-instance": "https://warcraft.wiki.gg/wiki/Archive_Vault"},
    }


def test_build_instance_page_no_llm_overview_and_bosses(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-archive-vault"
    instance_name = "Archive Vault"
    draft = build_instance_page(
        _fact_pack(instance_id, instance_name),
        _instance_evidence(instance_id, instance_name),
        {"lore_source": "instance_page"},
        section_blocks=[
            {
                "section_role": "adventurers",
                "text": "Bosses include /wiki/Archivist_Maelor and /wiki/Warden_Voss.",
            }
        ],
    )
    assert word_count(str(draft["overview"])) >= 170
    assert not lint_overview(str(draft["overview"]), instance_name=instance_name)
    enemy_names = {row["name"] for row in draft["key_enemies"]}
    assert "Archivist Maelor" in enemy_names
    assert "Warden Voss" in enemy_names
    assert not any(
        "key enemy presence tied to the instance narrative" in str(row.get("summary", "")).lower()
        for row in draft["key_enemies"]
    )
    provenance = draft.get("provenance") or {}
    assert provenance.get("identity_header")
    assert provenance.get("story_context")
    overview_words = word_count(str(draft["overview"]))
    if overview_words > 120:
        assert len(provenance["story_context"]) >= 2
    for card in draft["key_enemies"]:
        assert provenance.get("key_characters", {}).get(card["id"])


def test_instance_pools_do_not_use_zone_history(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-archive-vault"
    zone_id = "zone-example"
    zone_only = [
        {
            "subject_id": zone_id,
            "field_name": "history_digest",
            "evidence_items": [{"snippet": "Zone-only history that must not appear in instance overview."}],
            "build_meta": {"source_id": "src-zone"},
        }
    ]
    draft = build_instance_page(
        _fact_pack(instance_id, "Archive Vault"),
        _instance_evidence(instance_id, "Archive Vault"),
        None,
        parent_zone_evidence_rows=zone_only,
    )
    assert "Zone-only history" not in str(draft["overview"])


def test_build_scholomance_instance_page_from_faculty_section(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    faculty_html = (FIXTURES / "scholomance_faculty_section.html").read_text(encoding="utf-8")
    instance_id = "instance-scholomance"
    instance_name = "Scholomance"
    history = _long_history_snippet(instance_name)
    evidence = [
        {
            "subject_id": instance_id,
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": (
                        f"{instance_name} is a necromantic academy where Darkmaster Gandling "
                        "still commands hostile faculty beneath haunted halls."
                    ),
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-scholomance", "source_kind": "seed"},
        },
        {
            "subject_id": instance_id,
            "field_name": "history_digest",
            "evidence_items": [{"snippet": history, "section_role": "history"}],
            "build_meta": {"source_id": "src-scholomance", "source_kind": "seed"},
        },
        {
            "subject_id": instance_id,
            "field_name": "boss_pool",
            "evidence_items": [
                {
                    "snippet": faculty_html,
                    "section_role": "scholomance_faculty",
                }
            ],
            "build_meta": {"source_id": "src-scholomance", "source_kind": "seed"},
        },
    ]
    fact_pack = {
        "entity_id": instance_id,
        "entity_type": "instance",
        "name": instance_name,
        "parent_zone_id": "zone-western-plaguelands",
        "source_ids": ["src-scholomance"],
        "revision_ids": ["mw:100"],
        "source_urls": {"src-scholomance": "https://warcraft.wiki.gg/wiki/Scholomance"},
    }
    draft = build_instance_page(
        fact_pack,
        evidence,
        {"lore_source": "instance_page"},
        section_blocks=[{"section_role": "scholomance_faculty", "text": faculty_html}],
    )
    enemy_names = {row["name"] for row in draft["key_enemies"]}
    assert len(draft["key_enemies"]) >= 2
    assert "Darkmaster Gandling" in enemy_names
    assert "Jandice Barov" in enemy_names
    provenance = draft.get("provenance") or {}
    assert len(provenance.get("story_context") or []) <= 3
    assert len(provenance.get("identity_header") or []) <= 3
    for card in draft["key_enemies"]:
        assert provenance.get("key_characters", {}).get(card["id"])


def test_finalize_key_enemies_pointer_fallback_when_used_empty(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")

    def _summary_without_used(*_args, **_kwargs):
        return (
            "Darkmaster Gandling commands Scholomance faculty and anchors the instance's necromantic hierarchy.",
            [],
        )

    monkeypatch.setattr(
        "pipeline.generate.draft.wiki_first.synthesize_key_enemy_summary",
        _summary_without_used,
    )
    candidate = BossCandidate(
        boss_id="character-darkmaster-gandling",
        name="Darkmaster Gandling",
        wiki_url="https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
        source_section_role="scholomance_faculty",
    )
    boss_pool = [
        {
            "snippet": "Darkmaster Gandling leads the faculty wing of Scholomance.",
            "section_role": "scholomance_faculty",
            "source_id": "src-scholomance",
        }
    ]
    candidate.profile_pool = boss_pool
    cards, provenance, _used = _finalize_key_enemies(
        instance_name="Scholomance",
        boss_candidates=[candidate],
        boss_pool=boss_pool,
        revision_map={"src-scholomance": "mw:100"},
    )
    assert len(cards) == 1
    assert cards[0]["name"] == "Darkmaster Gandling"
    assert provenance["character-darkmaster-gandling"]
