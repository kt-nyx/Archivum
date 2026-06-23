from __future__ import annotations

import pytest

from pipeline.discovery.entity_typing import should_reject_location_title
from pipeline.discovery.location_discovery import (
    classify_location_candidate,
    score_location_candidate,
)
from pipeline.generate.draft.location_scoring import (
    _INCLUDE_CLASSIFICATIONS,
    classification_to_location_type,
)


def _candidate(name: str, *, role: str = "maps_subregions") -> dict:
    return {
        "location_id": f"location-{name.lower().replace(' ', '-')}",
        "name": name,
        "source_section_role": role,
    }


def test_wpl_landmarks_reach_include_threshold_with_seed_text() -> None:
    seed_text = "Western Plaguelands contains Andorhal, Hearthglen, and Caer Darrow among its ruined settlements."
    for name in ("Andorhal", "Hearthglen", "Caer Darrow"):
        score, decision, _reasons = score_location_candidate(_candidate(name), seed_text=seed_text)
        assert score >= 0.7, f"{name} scored {score}"
        assert decision == "include"


def test_borderline_location_score_promotes_to_include() -> None:
    score, decision, reasons = score_location_candidate(
        _candidate("Andorhal", role="history"),
        seed_text="Western Plaguelands history mentions Andorhal repeatedly.",
    )
    assert round(score, 2) == 0.65
    assert decision == "include"
    assert "borderline_include" in reasons


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Charred Outpost", "outpost"),
        ("Menders' Stead", "outpost"),
        ("Uther's Tomb", "landmark"),
        ("Durnholde Keep", "fortress"),
        ("Northridge Lumber Mill", "town"),
        ("Tarren Mill", "town"),
        ("Darrowmere Lake", "natural_feature"),
        ("Ruins of Andorhal", "ruins"),
        ("Stormwind City", "city"),
        # Proper-noun-only names carry no descriptive token (no pre-fetch category
        # signal) and intentionally fall through to the generic candidate type.
        ("Andorhal", "major_location_candidate"),
        ("Caer Darrow", "major_location_candidate"),
        ("Hearthglen", "major_location_candidate"),
    ],
)
def test_classify_location_candidate_types_from_name_tokens(name: str, expected: str) -> None:
    assert classify_location_candidate(name, hard_reject_reasons=[]) == expected


def test_hard_reject_short_circuits_classification() -> None:
    assert classify_location_candidate("Anything", hard_reject_reasons=["rpg_marker"]) == "reject"


def test_typed_classifications_are_included_and_map_to_location_type() -> None:
    for classification in ("outpost", "landmark", "fortress", "town", "ruins", "natural_feature"):
        assert classification in _INCLUDE_CLASSIFICATIONS
        assert classification_to_location_type(classification) == classification
    # The generic candidate token collapses to the published major_location value.
    assert classification_to_location_type("major_location_candidate") == "major_location"


def test_typed_landmark_preserves_generic_score_path() -> None:
    # A descriptive name that now types as 'outpost' must score identically to the
    # pre-change 'major_location_candidate' path (named_place bonus still applies).
    score, decision, reasons = score_location_candidate(
        _candidate("Charred Outpost", role="maps_subregions"),
        seed_text="Western Plaguelands contains the Charred Outpost.",
    )
    assert decision == "include"
    assert "named_place" in reasons


def test_junk_location_titles_are_rejected() -> None:
    for title in ("Lore", "ADP", "Scourge", "Argent Dawn"):
        reject, reasons = should_reject_location_title(title, zone_name="Western Plaguelands")
        assert reject, f"{title} should be rejected ({reasons})"


def test_real_landmarks_are_not_rejected() -> None:
    for title in ("Andorhal", "Hearthglen", "Caer Darrow"):
        reject, _reasons = should_reject_location_title(
            title,
            zone_name="Western Plaguelands",
            source_section_role="maps_subregions",
        )
        assert not reject, title
