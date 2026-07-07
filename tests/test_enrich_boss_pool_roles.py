from __future__ import annotations

from pipeline.discovery.enrich import _instance_seed_field_names
from pipeline.discovery.instance_bosses import boss_section_role_matches, is_boss_section_role


def test_shared_boss_section_role_matcher() -> None:
    # Structural roster roles match; a school-themed "Faculty" heading is not a hardcoded token
    # (Slice 14) — Scholomance's roster reaches boss_pool via its per-dungeon table instead.
    assert is_boss_section_role("dungeon_scholomance")
    assert not is_boss_section_role("scholomance_faculty")
    assert boss_section_role_matches("denizens")
    assert is_boss_section_role("walkthrough")


def test_instance_seed_field_names_routes_boss_pool_for_retail_roles() -> None:
    assert "boss_pool" in _instance_seed_field_names("dungeon_scholomance", lead_emitted=0)
    assert "boss_pool" in _instance_seed_field_names("denizens", lead_emitted=0)
    assert "boss_pool" in _instance_seed_field_names("dungeon_journal", lead_emitted=0)
    assert "boss_pool" not in _instance_seed_field_names("getting_there", lead_emitted=0)
