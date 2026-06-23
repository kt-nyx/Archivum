from __future__ import annotations

from pipeline.discovery.pilot_questline_registry import (
    WPL_ZONE_ID,
    anchor_by_card_id,
    included_card_ids,
    load_registry,
    registry_path_for_zone,
    structural_expectations_for_zone,
)


def test_registry_path_points_at_pipeline_data() -> None:
    path = registry_path_for_zone(WPL_ZONE_ID)
    assert path is not None
    assert path.exists()
    assert "pipeline" in str(path)
    assert "data" in str(path)


def test_load_registry_included_and_excluded_ids() -> None:
    registry = load_registry(WPL_ZONE_ID)
    assert registry is not None
    included = included_card_ids(registry)
    excluded = {arc["id"] for arc in registry.get("excluded_arcs", []) if isinstance(arc, dict)}
    assert included == {
        "ql-andorhal-alliance",
        "ql-andorhal-horde",
        "ql-hearthglen-tirion-legacy",
        "ql-gahrrons-withering",
    }
    assert "ql-northridge-redpine" in excluded
    assert "ql-gahrrons-withering" not in excluded
    assert included.isdisjoint(excluded)


def test_structural_expectations_for_wpl() -> None:
    expectations = structural_expectations_for_zone(WPL_ZONE_ID)
    assert expectations is not None
    assert expectations.expected_card_count == 4
    anchors = anchor_by_card_id(load_registry(WPL_ZONE_ID) or {})
    assert anchors["ql-andorhal-alliance"] == "Hero's Call: Western Plaguelands!"
