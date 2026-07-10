from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.discovery.instance_bosses import (
    collect_boss_candidates,
    mine_narrative_character_candidates,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "instance"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


# Narrative fallback fixtures are retained as link-extraction probes. Slice 1
# deliberately abstains when no target-page entity-kind evidence is available;
# Slice 3 adds participant admission.
NARRATIVE_CASES = [
    ("icc_narrative.json", "Tirion Fordring"),
    ("ulduar_narrative.json", "Odyn"),
]

# (fixture, NPC that must be extracted from the roster section)
ROSTER_CASES = [
    ("blackrock_depths_denizens.json", "Marshal Windsor"),
    ("subregion_nested.json", "Plugger Spazzring"),
]


@pytest.mark.parametrize("fixture,marquee", NARRATIVE_CASES)
def test_narrative_fallback_matrix(monkeypatch, fixture: str, marquee: str) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    _ = marquee
    data = _load(fixture)

    def _run() -> list[str]:
        candidates = mine_narrative_character_candidates(
            data["section_blocks"],
            instance_name=data["instance_name"],
            structured_links=data.get("structured_links", []),
            max_count=10,
        )
        return [candidate.name for candidate in candidates]

    names = _run()
    assert isinstance(names, list), fixture
    assert all(
        candidate.wiki_url
        for candidate in mine_narrative_character_candidates(
            data["section_blocks"],
            instance_name=data["instance_name"],
            structured_links=data.get("structured_links", []),
            max_count=10,
        )
    ), f"{fixture}: every narrative candidate must carry a wiki link"
    assert _run() == names, f"{fixture}: narrative fallback is not deterministic"


@pytest.mark.parametrize("fixture,expected_npc", ROSTER_CASES)
def test_roster_extraction_matrix(monkeypatch, fixture: str, expected_npc: str) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    data = _load(fixture)

    def _run() -> list[str]:
        candidates = collect_boss_candidates(
            section_blocks=data["section_blocks"],
            instance_name=data["instance_name"],
            boss_pool_items=[],
            structured_links=data.get("structured_links", []),
        )
        return [candidate.name for candidate in candidates]

    names = _run()
    assert names, f"{fixture}: roster extraction found no candidates"
    assert expected_npc in names, f"{fixture}: expected {expected_npc!r} in {names}"
    assert _run() == names, f"{fixture}: roster extraction is not deterministic"


def test_subregion_nesting_requires_parent_awareness() -> None:
    """The subregion fixture's NPCs sit under place-named leaves; only the
    roster parent (`dungeon_denizens`) makes them roster-bearing."""
    data = _load("subregion_nested.json")
    leaf_roles = {block["section_role"] for block in data["section_blocks"]}
    from pipeline.discovery.instance_bosses import is_boss_section_role

    assert leaf_roles, "fixture has no section blocks"
    assert not any(is_boss_section_role(role) for role in leaf_roles), (
        "subregion fixture leaves must be non-roster to exercise parent awareness"
    )
    assert all(
        block.get("parent_section_role") == "dungeon_denizens" for block in data["section_blocks"]
    )
    candidates = collect_boss_candidates(
        section_blocks=data["section_blocks"],
        instance_name=data["instance_name"],
        boss_pool_items=[],
    )
    assert candidates, "parent awareness failed: no candidates from subregion-nested roster"
