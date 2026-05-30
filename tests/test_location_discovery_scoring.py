from __future__ import annotations

from pipeline.discovery.entity_typing import should_reject_location_title
from pipeline.discovery.location_discovery import score_location_candidate


def _candidate(name: str, *, role: str = "maps_subregions") -> dict:
    return {
        "location_id": f"location-{name.lower().replace(' ', '-')}",
        "name": name,
        "source_section_role": role,
    }


def test_wpl_landmarks_reach_include_threshold_with_seed_text() -> None:
    seed_text = (
        "Western Plaguelands contains Andorhal, Hearthglen, and Caer Darrow among its ruined settlements."
    )
    for name in ("Andorhal", "Hearthglen", "Caer Darrow"):
        score, decision, _reasons = score_location_candidate(_candidate(name), seed_text=seed_text)
        assert score >= 0.7, f"{name} scored {score}"
        assert decision == "include"


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
