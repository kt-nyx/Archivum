from __future__ import annotations

from pipeline.discovery.instance_bosses import (
    BossCandidate,
    merge_key_character_cast,
    merged_cast_candidates,
)


def _candidate(name: str) -> BossCandidate:
    return BossCandidate(
        boss_id=f"character-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url=f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
        source_section_role="bosses",
    )


def test_merge_floor_before_llm() -> None:
    pool = [_candidate("Floor Boss"), _candidate("Llm Pick")]
    merged, reasons = merge_key_character_cast(
        pool,
        must_include_names=["Floor Boss"],
        llm_ordered_names=["Llm Pick"],
        max_count=10,
    )
    assert merged == ["Floor Boss", "Llm Pick"]
    assert reasons == {
        "Floor Boss": "must_include_floor",
        "Llm Pick": "llm_selected",
    }


def test_merge_duplicate_floor_wins() -> None:
    pool = [_candidate("Shared Name")]
    merged, reasons = merge_key_character_cast(
        pool,
        must_include_names=["Shared Name"],
        llm_ordered_names=["Shared Name"],
        max_count=10,
    )
    assert merged == ["Shared Name"]
    assert reasons["Shared Name"] == "must_include_floor"


def test_merge_floor_overflow_truncates() -> None:
    pool = [_candidate(f"Boss {index}") for index in range(11)]
    floor = [candidate.name for candidate in pool]
    merged, reasons = merge_key_character_cast(
        pool,
        must_include_names=floor,
        llm_ordered_names=["Boss 99"],
        max_count=10,
    )
    assert len(merged) == 10
    assert merged == floor[:10]
    assert all(reasons[name] == "must_include_floor" for name in merged)
    assert "Boss 99" not in merged


def test_merge_llm_empty_returns_floor_only() -> None:
    pool = [_candidate("Floor Boss")]
    merged, reasons = merge_key_character_cast(
        pool,
        must_include_names=["Floor Boss"],
        llm_ordered_names=[],
        max_count=10,
    )
    assert merged == ["Floor Boss"]
    assert reasons == {"Floor Boss": "must_include_floor"}


def test_merge_skips_must_include_not_in_pool() -> None:
    pool = [_candidate("In Pool")]
    merged, reasons = merge_key_character_cast(
        pool,
        must_include_names=["Missing Boss", "In Pool"],
        llm_ordered_names=[],
        max_count=10,
    )
    assert merged == ["In Pool"]
    assert "Missing Boss" not in reasons


def test_merged_cast_candidates_preserves_order() -> None:
    pool = [_candidate("Second"), _candidate("First")]
    cast = merged_cast_candidates(pool, ["First", "Second"], instance_name="Test")
    assert [row.name for row in cast] == ["First", "Second"]
