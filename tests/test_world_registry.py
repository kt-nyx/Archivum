from __future__ import annotations

import pytest

from pipeline.discovery.entity_typing import (
    is_valid_quest_graph_link,
    should_reject_location_title,
    should_skip_registry_traversal,
)
from pipeline.discovery.world_registry import load_world_registry, registry_index


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


def test_location_title_rejects_dating_convention_pages() -> None:
    reject, reasons = should_reject_location_title("Third War (28 ADP)")
    assert reject
    assert "dating_convention" in reasons
