from __future__ import annotations

from pipeline.discovery.instance_bosses import collect_boss_candidates, should_reject_boss_title


def test_collect_boss_candidates_from_encounter_section() -> None:
    section_blocks = [
        {
            "section_role": "adventurers",
            "text": "Bosses include [[/wiki/Archivist_Maelor|Archivist Maelor]] and [[/wiki/Warden_Voss|Warden Voss]].",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Archive Vault",
        boss_pool_items=[],
    )
    names = {row.name for row in candidates}
    assert "Archivist Maelor" in names
    assert "Warden Voss" in names
    assert all(row.boss_id.startswith("character-") for row in candidates)


def test_boss_pool_items_merge_with_section_blocks() -> None:
    boss_pool_items = [
        {
            "snippet": "Encounter with /wiki/Custodian_Lira who guards the inner vault.",
            "section_role": "encounters",
            "source_id": "src-instance",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Archive Vault",
        boss_pool_items=boss_pool_items,
    )
    assert len(candidates) == 1
    assert candidates[0].name == "Custodian Lira"


def test_rejects_geography_and_instance_self_titles() -> None:
    assert should_reject_boss_title("Archive Vault", instance_name="Archive Vault")
    assert should_reject_boss_title("Eastern Kingdoms", instance_name="Archive Vault")
