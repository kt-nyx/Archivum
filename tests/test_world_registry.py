from __future__ import annotations

import pytest

from pipeline.discovery.entity_typing import (
    is_valid_quest_graph_link,
    should_skip_registry_traversal,
)
from pipeline.discovery.world_registry import (
    RegistryEntry,
    _ingest_organization_categories,
    _parent_kind_from_entries,
    load_world_registry,
    registry_index,
)


@pytest.fixture(scope="module")
def registry_loaded() -> None:
    payload = load_world_registry()
    assert payload.get("entry_count", 0) > 100


def test_world_registry_contains_pilot_zones(registry_loaded: None) -> None:
    index = registry_index()
    for title in ("western plaguelands", "eastern plaguelands", "scholomance"):
        assert title in index, f"missing registry entry for {title!r}"


def test_world_registry_contains_pilot_places(registry_loaded: None) -> None:
    index = registry_index()
    for title in ("andorhal", "hearthglen"):
        row = index.get(title)
        assert row is not None, f"missing registry entry for {title!r}"
        assert "place" in row.get("kinds", [])


def test_quest_graph_rejects_registry_zone_titles(registry_loaded: None) -> None:
    valid, reasons = is_valid_quest_graph_link(
        "/wiki/Eastern_Plaguelands", zone_name="Example Zone"
    )
    assert not valid
    assert any("registry" in reason or "denylist" in reason for reason in reasons)


def test_traversal_blocks_zone_pages_for_quest_role(registry_loaded: None) -> None:
    skip, reasons = should_skip_registry_traversal(
        "/wiki/Eastern_Kingdoms",
        auxiliary_role="quest",
        zone_name="Example Zone",
    )
    assert skip
    assert reasons


def test_traversal_allows_location_profile_for_subzone_not_in_registry(
    registry_loaded: None,
) -> None:
    skip, _ = should_skip_registry_traversal(
        "/wiki/Brill",
        auxiliary_role="location_profile",
        zone_name="Example Zone",
    )
    assert not skip


def test_traversal_allows_manifest_instance_for_location_profile(registry_loaded: None) -> None:
    skip, _ = should_skip_registry_traversal(
        "/wiki/Scholomance",
        auxiliary_role="location_profile",
        zone_name="Example Zone",
        allowed_instance_titles=frozenset({"Scholomance"}),
    )
    assert not skip


def test_traversal_blocks_manifest_instance_for_quest_role(registry_loaded: None) -> None:
    skip, reasons = should_skip_registry_traversal(
        "/wiki/Scholomance",
        auxiliary_role="quest",
        zone_name="Example Zone",
        allowed_instance_titles=frozenset({"Scholomance"}),
    )
    assert skip
    assert reasons


def test_quest_graph_rejects_registry_person_titles(registry_loaded: None) -> None:
    valid, reasons = is_valid_quest_graph_link(
        "/wiki/High_General_Abbendis",
        zone_name="Example Zone",
    )
    assert not valid
    assert any("registry_person" in reason for reason in reasons)


def test_traversal_blocks_person_for_quest_role(registry_loaded: None) -> None:
    skip, reasons = should_skip_registry_traversal(
        "/wiki/High_General_Abbendis",
        auxiliary_role="quest",
        zone_name="Example Zone",
    )
    assert skip
    assert any("registry_person" in reason for reason in reasons)


def test_traversal_blocks_place_for_quest_role(registry_loaded: None) -> None:
    skip, reasons = should_skip_registry_traversal(
        "/wiki/Andorhal",
        auxiliary_role="quest",
        zone_name="Western Plaguelands",
    )
    assert skip
    assert any("registry_place" in reason for reason in reasons)


def test_traversal_allows_place_for_location_profile(registry_loaded: None) -> None:
    skip, _ = should_skip_registry_traversal(
        "/wiki/Andorhal",
        auxiliary_role="location_profile",
        zone_name="Western Plaguelands",
    )
    assert not skip


def _entry(title: str, kinds: tuple[str, ...]) -> RegistryEntry:
    normalized = title.lower()
    return RegistryEntry(
        title=title,
        normalized_title=normalized,
        wiki_path=f"/wiki/{title.replace(' ', '_')}",
        kinds=kinds,
        source_categories=("Category:Test",),
    )


def test_registry_includes_organization_kind_with_affiliations(registry_loaded: None) -> None:
    """Slice 12: the committed registry always carries organization entries."""
    index = registry_index()
    orgs = [row for row in index.values() if "organization" in row.get("kinds", [])]
    assert len(orgs) > 100, "expected the rebuilt registry to seed organization entries"
    crusade = index.get("argent crusade")
    assert crusade is not None and "organization" in crusade["kinds"]
    # Umbrella affiliations come from Alliance/Horde faction category membership.
    silver_covenant = index.get("silver covenant")
    assert silver_covenant is not None
    assert "alliance" in silver_covenant.get("affiliations", [])


def test_ingest_organization_categories_seeds_kinds_and_affiliations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org seeds produce kind="organization" entries; umbrella affiliations come from
    Alliance/Horde faction category memberships; racial org categories are swept from
    the wiki's own Category:Organizations by race subcategory list; concept/list
    articles ("Faction", "Alliance organizations") never become entries."""
    members_by_category: dict[str, list[dict[str, object]]] = {
        "Category:Organizations": [
            {"ns": 0, "title": "Faction"},
            {"ns": 0, "title": "Alliance organizations"},
            {"ns": 0, "title": "Alliance of Lordaeron"},
        ],
        "Category:Factions": [
            {"ns": 0, "title": "Alliance"},
            {"ns": 0, "title": "Argent Crusade"},
            {"ns": 0, "title": "Silver Covenant"},
            {"ns": 14, "title": "Category:Alliance factions"},
        ],
        "Category:Alliance factions": [{"ns": 0, "title": "Silver Covenant"}],
        "Category:Horde factions": [{"ns": 0, "title": "Defilers"}],
        "Category:Organizations by race": [
            {"ns": 14, "title": "Category:Troll organizations"},
            {"ns": 0, "title": "Stray article"},
        ],
        "Category:Troll organizations": [{"ns": 0, "title": "Darkspear tribe"}],
    }

    def fake_fetch(category: str, **_kwargs: object) -> list[dict[str, object]]:
        return members_by_category.get(category, [])

    monkeypatch.setattr(
        "pipeline.discovery.world_registry._fetch_category_members", fake_fetch
    )
    entries: dict[str, RegistryEntry] = {}
    _ingest_organization_categories(entries, sleep_seconds=0, cache={}, cache_path=None)

    assert "faction" not in entries
    assert "alliance organizations" not in entries
    assert entries["alliance of lordaeron"].kinds == ("organization",)
    assert entries["alliance of lordaeron"].affiliations == ()
    assert entries["argent crusade"].affiliations == ()  # neutral = no umbrella category
    # Membership in both Category:Factions and Category:Alliance factions unions.
    assert entries["silver covenant"].kinds == ("organization",)
    assert entries["silver covenant"].affiliations == ("alliance",)
    assert entries["defilers"].affiliations == ("horde",)
    # Racial org categories are discovered from the subcat sweep, never hand-listed.
    assert entries["darkspear tribe"].kinds == ("organization",)
    assert entries["darkspear tribe"].source_categories == ("Category:Troll organizations",)


def test_parent_kind_from_entries_uses_category_kinds_not_name_markers() -> None:
    """Slice 11: subzone parents classify from wiki category seeds, never name tokens."""
    entries = {
        "example depths": _entry("Example Depths", ("instance",)),
        "example vale": _entry("Example Vale", ("zone",)),
    }
    # An instance-kind entry classifies as instance regardless of its name.
    assert _parent_kind_from_entries(entries, "Example Depths") == "instance"
    # A zone-kind entry stays a zone even when its name carries an old marker token
    # ("Vale" carried no marker, "Depths" did — the lookup ignores both).
    assert _parent_kind_from_entries(entries, "Example Vale") == "zone"
    # Unknown parents (not in any seeded category) default to zone.
    assert _parent_kind_from_entries(entries, "Uncatalogued Hollow") == "zone"
