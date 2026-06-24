from __future__ import annotations

from pathlib import Path

from pipeline.discovery.instance_bosses import BossCandidate
from pipeline.generate.draft.instance_lint import MIN_OVERVIEW_WORDS, lint_overview
from pipeline.generate.draft.pages import build_instance_page
from pipeline.generate.draft.pages.key_characters import _finalize_key_characters
from pipeline.generate.draft.prose_lint import word_count

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
    assert word_count(str(draft["overview"])) >= MIN_OVERVIEW_WORDS
    assert not lint_overview(str(draft["overview"]), instance_name=instance_name)
    enemy_names = {row["name"] for row in draft["key_characters"]}
    assert "Archivist Maelor" in enemy_names
    assert "Warden Voss" in enemy_names
    assert not any(
        "key enemy presence tied to the instance narrative" in str(row.get("summary", "")).lower()
        for row in draft["key_characters"]
    )
    provenance = draft.get("provenance") or {}
    assert provenance.get("identity_header")
    assert provenance.get("story_context")
    overview_words = word_count(str(draft["overview"]))
    if overview_words > 120:
        assert len(provenance["story_context"]) >= 2
    for card in draft["key_characters"]:
        assert provenance.get("key_characters", {}).get(card["id"])


def test_instance_pools_do_not_use_zone_history(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-archive-vault"
    zone_id = "zone-example"
    zone_only = [
        {
            "subject_id": zone_id,
            "field_name": "history_digest",
            "evidence_items": [
                {"snippet": "Zone-only history that must not appear in instance overview."}
            ],
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
    enemy_names = {row["name"] for row in draft["key_characters"]}
    assert len(draft["key_characters"]) >= 2
    assert "Darkmaster Gandling" in enemy_names
    assert "Jandice Barov" in enemy_names
    assert any(card.get("wiki_ref") for card in draft["key_characters"])
    # Faculty roster is an enemy-lean section, so deterministic classification
    # takes these off the uncertain default (Slice I3).
    assert all(
        card.get("role") in {"enemy", "ally", "neutral", "uncertain"}
        for card in draft["key_characters"]
    )
    assert all(card.get("role") == "enemy" for card in draft["key_characters"])
    assert all(card.get("decision_reason_codes") for card in draft["key_characters"])
    provenance = draft.get("provenance") or {}
    assert len(provenance.get("story_context") or []) <= 3
    assert len(provenance.get("identity_header") or []) <= 3
    for card in draft["key_characters"]:
        assert provenance.get("key_characters", {}).get(card["id"])


def test_build_instance_page_wires_scoped_links_and_parent_roles(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-archive-vault"
    instance_name = "Archive Vault"
    history = _long_history_snippet(instance_name)
    evidence = [
        {
            "subject_id": instance_id,
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": (
                        f"{instance_name} is a blighted academy where Archivist Maelor and Warden Voss "
                        "still guard the haunted inner vault."
                    ),
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-instance", "source_kind": "seed"},
        },
        {
            "subject_id": instance_id,
            "field_name": "history_digest",
            "evidence_items": [{"snippet": history, "section_role": "history"}],
            "build_meta": {"source_id": "src-instance", "source_kind": "seed"},
        },
        {
            "subject_id": instance_id,
            "field_name": "boss_pool",
            "evidence_items": [
                {
                    "snippet": (
                        "Archivist Maelor hoards forbidden tomes while Warden Voss bars the vault doors "
                        "against intruders."
                    ),
                    "section_role": "denizens",
                }
            ],
            "build_meta": {"source_id": "src-instance", "source_kind": "seed"},
        },
    ]
    snapshots = [
        {
            "entity_id": instance_id,
            "entity_type": "instance",
            "structured_links": [
                {
                    "href": "/wiki/Archivist_Maelor",
                    "label": "Archivist Maelor",
                    "section_role": "denizens",
                },
                {"href": "/wiki/Patch_3.0.2", "label": "Patch 3.0.2", "section_role": "lead"},
            ],
        }
    ]
    draft = build_instance_page(
        _fact_pack(instance_id, instance_name),
        evidence,
        {"lore_source": "instance_page"},
        section_blocks=[
            {
                "section_role": "vault_catacombs",
                "parent_section_role": "dungeon_denizens",
                "text": '<a href="/wiki/Warden_Voss">Warden Voss</a>',
            }
        ],
        snapshots=snapshots,
    )
    names = {row["name"] for row in draft["key_characters"]}
    assert "Archivist Maelor" in names  # scoped structured link (roster role) registered
    assert "Warden Voss" in names  # parent_section_role made a non-roster leaf roster-bearing
    assert "Patch 3.0.2" not in names  # non-roster (lead) structured link scoped out
    for card in draft["key_characters"]:
        assert draft.get("provenance", {}).get("key_characters", {}).get(card["id"])


def _parent_lore_snippet(instance_name: str) -> str:
    return (
        f"{instance_name} is one of the wings of the great draenei complex, sealed away after the "
        "draenei were slaughtered and their burial vaults were defiled by invading ethereals who "
        f"sought the naaru relics interred within. Adventurers descend into {instance_name} to halt "
        "the ethereal Nexus-Prince and recover the stolen energies before they can be channeled into "
        "weapons of devastation across the shattered world beyond the temple ruins and crypts."
    )


def test_sparse_instance_fuses_cross_page_lore_with_provenance(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-mana-tombs"
    instance_name = "Mana-Tombs"
    evidence = [
        {
            "subject_id": instance_id,
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": f"{instance_name} is a draenei burial wing overrun by ethereal raiders.",
                    "section_role": "lead",
                }
            ],
            "build_meta": {
                "source_id": "src-instance",
                "source_kind": "seed",
                "lore_scope": "instance",
            },
        },
        {
            "subject_id": instance_id,
            "field_name": "history_digest",
            "evidence_items": [{"snippet": "A short stub.", "section_role": "history"}],
            "build_meta": {
                "source_id": "src-instance",
                "source_kind": "seed",
                "lore_scope": "instance",
            },
        },
        {
            "subject_id": instance_id,
            "field_name": "parent_lore_pool",
            "evidence_items": [
                {"snippet": _parent_lore_snippet(instance_name), "section_role": "history"}
            ],
            "build_meta": {
                "source_id": "src-parent",
                "source_kind": "auxiliary",
                "auxiliary_role": "parent_lore",
                "lore_scope": "parent",
                "lore_source_title": "Auchindoun",
            },
        },
    ]
    fact_pack = {
        "entity_id": instance_id,
        "entity_type": "instance",
        "name": instance_name,
        "parent_zone_id": "zone-terokkar-forest",
        "source_ids": ["src-instance", "src-parent"],
        "revision_ids": ["mw:100", "mw:200"],
        "source_urls": {
            "src-instance": "https://warcraft.wiki.gg/wiki/Mana-Tombs",
            "src-parent": "https://warcraft.wiki.gg/wiki/Auchindoun",
        },
    }
    draft = build_instance_page(fact_pack, evidence, {"lore_source": "instance_page"})
    assert not lint_overview(str(draft["overview"]), instance_name=instance_name)
    # Cross-page lore was fused -> source flips to linked_lore_page with a clear reason,
    # and the parent page is cited in story-context provenance.
    assert draft["lore_source"] == "linked_lore_page"
    assert draft["lore_source_reason"] == "cross_page_fusion"
    story_sources = {p["source_id"] for p in draft["provenance"]["story_context"]}
    assert "src-parent" in story_sources


def test_sparse_instance_excludes_non_naming_related_lore_offline(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-mana-tombs"
    instance_name = "Mana-Tombs"
    # ~50 words of instance-owned history: sparse, but enough to synthesize an overview.
    own_history = (
        f"{instance_name} is a draenei burial wing whose vaults were breached when ethereal "
        "raiders descended seeking the relics interred below. Defenders fell quickly and the "
        "halls were left haunted, with adventurers later sent to drive the intruders out before "
        "the stolen energies could be turned against the living world beyond."
    )
    evidence = [
        {
            "subject_id": instance_id,
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": f"{instance_name} is a defiled draenei burial wing.",
                    "section_role": "lead",
                }
            ],
            "build_meta": {
                "source_id": "src-instance",
                "source_kind": "seed",
                "lore_scope": "instance",
            },
        },
        {
            "subject_id": instance_id,
            "field_name": "history_digest",
            "evidence_items": [{"snippet": own_history, "section_role": "history"}],
            "build_meta": {
                "source_id": "src-instance",
                "source_kind": "seed",
                "lore_scope": "instance",
            },
        },
        {
            "subject_id": instance_id,
            "field_name": "related_lore_pool",
            "evidence_items": [
                {
                    "snippet": (
                        "Outland is a shattered realm of floating continents and warring factions."
                    ),
                    "section_role": "history",
                }
            ],
            "build_meta": {
                "source_id": "src-related",
                "auxiliary_role": "related_lore",
                "lore_scope": "related",
            },
        },
    ]
    fact_pack = dict(_fact_pack(instance_id, instance_name))
    fact_pack["source_ids"] = ["src-instance", "src-related"]
    fact_pack["revision_ids"] = ["mw:100", "mw:200"]
    fact_pack["source_urls"] = {
        "src-instance": "https://warcraft.wiki.gg/wiki/Mana-Tombs",
        "src-related": "https://warcraft.wiki.gg/wiki/Outland",
    }
    draft = build_instance_page(fact_pack, evidence, {"lore_source": "instance_page"})
    # Related page neither names the instance nor is LLM-affirmed offline -> never fused.
    assert "floating continents" not in str(draft["overview"])
    assert draft["lore_source"] == "instance_page"
    story_sources = {p["source_id"] for p in draft["provenance"]["story_context"]}
    assert "src-related" not in story_sources


def test_rich_instance_ignores_cross_page_lore(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    instance_id = "instance-archive-vault"
    instance_name = "Archive Vault"
    evidence = _instance_evidence(instance_id, instance_name)
    # A tangential parent page that does NOT name the instance must never be fused into
    # a rich instance's overview (overreach control + no regression).
    evidence.append(
        {
            "subject_id": instance_id,
            "field_name": "parent_lore_pool",
            "evidence_items": [
                {
                    "snippet": "The broader citadel complex has many unrelated wings and stories.",
                    "section_role": "history",
                }
            ],
            "build_meta": {
                "source_id": "src-parent",
                "auxiliary_role": "parent_lore",
                "lore_scope": "parent",
            },
        }
    )
    fact_pack = dict(_fact_pack(instance_id, instance_name))
    fact_pack["source_ids"] = ["src-instance", "src-parent"]
    fact_pack["revision_ids"] = ["mw:100", "mw:200"]
    fact_pack["source_urls"] = {
        "src-instance": "https://warcraft.wiki.gg/wiki/Archive_Vault",
        "src-parent": "https://warcraft.wiki.gg/wiki/Citadel",
    }
    draft = build_instance_page(fact_pack, evidence, {"lore_source": "instance_page"})
    assert "unrelated wings" not in str(draft["overview"])
    assert draft["lore_source"] == "instance_page"
    story_sources = {p["source_id"] for p in draft["provenance"]["story_context"]}
    assert "src-parent" not in story_sources


def test_finalize_key_characters_pointer_fallback_when_used_empty(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")

    def _summary_without_used(*_args, **_kwargs):
        return (
            "Darkmaster Gandling commands Scholomance faculty and anchors the instance's necromantic hierarchy.",
            [],
        )

    monkeypatch.setattr(
        "pipeline.generate.draft.pages.key_characters.synthesize_key_character_summary",
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
    cards, provenance, _used = _finalize_key_characters(
        instance_name="Scholomance",
        boss_candidates=[candidate],
        boss_pool=boss_pool,
        revision_map={"src-scholomance": "mw:100"},
    )
    assert len(cards) == 1
    assert cards[0]["name"] == "Darkmaster Gandling"
    assert provenance["character-darkmaster-gandling"]


def test_finalize_key_characters_drops_non_floor_narrative_fallback(monkeypatch) -> None:
    # WS-4: a non-floor candidate sourced only from a narrative fallback (no boss/denizen
    # section signal) is dropped rather than padding the roster with a low-confidence card.
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.key_characters.synthesize_key_character_summary",
        lambda *a, **k: ("Lich King looms over the campaign from afar.", ["src-x"]),
    )
    boss_pool = [
        {
            "snippet": "The Lich King is mentioned in passing.",
            "section_role": "other",
            "source_id": "src-x",
        }
    ]
    narrative = BossCandidate(
        boss_id="character-lich-king",
        name="Lich King",
        wiki_url="https://warcraft.wiki.gg/wiki/Lich_King",
        source_section_role="narrative_fallback",
    )
    narrative.profile_pool = boss_pool
    cards, _prov, _used = _finalize_key_characters(
        instance_name="Scholomance",
        boss_candidates=[narrative],
        boss_pool=boss_pool,
        revision_map={"src-x": "mw:1"},
    )
    assert cards == []

    # The same candidate survives when it is on the must-include floor.
    cards_floor, _p, _u = _finalize_key_characters(
        instance_name="Scholomance",
        boss_candidates=[narrative],
        boss_pool=boss_pool,
        revision_map={"src-x": "mw:1"},
        selection_reasons={"Lich King": "must_include_floor"},
    )
    assert [c["name"] for c in cards_floor] == ["Lich King"]
