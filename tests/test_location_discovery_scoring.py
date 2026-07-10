from __future__ import annotations

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


def test_location_score_uses_source_relationship_not_title_shape() -> None:
    score, decision, reasons = score_location_candidate(
        _candidate("Andorhal", role="history"),
        seed_text="Western Plaguelands history mentions Andorhal repeatedly.",
    )
    assert round(score, 2) == 0.75
    assert decision == "include"
    assert "seed_mention" in reasons


def test_location_discovery_does_not_type_a_place_from_its_title() -> None:
    for name in ("Example Keep", "Example Tomb", "Example Species", "Example Person"):
        assert classify_location_candidate(name, hard_reject_reasons=[]) == "major_location_candidate"


def test_hard_reject_short_circuits_classification() -> None:
    assert classify_location_candidate("Anything", hard_reject_reasons=["rpg_marker"]) == "reject"


def test_neutral_discovery_classification_maps_to_published_default() -> None:
    # Published types are resolved from target-page categories/infoboxes, not names.
    assert classification_to_location_type("major_location_candidate") == "major_location"
    assert "major_location_candidate" in _INCLUDE_CLASSIFICATIONS


def test_title_shape_does_not_affect_location_score() -> None:
    score, decision, reasons = score_location_candidate(
        _candidate("Charred Outpost", role="maps_subregions"),
        seed_text="Western Plaguelands contains the Charred Outpost.",
    )
    assert decision == "include"
    assert "named_place" not in reasons
