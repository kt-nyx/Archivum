from __future__ import annotations

import pipeline.generate.draft.prose_synthesis as synth
from pipeline.generate.draft.location_scoring import (
    LocationCandidate,
    location_type_from_signals,
    score_location_candidate,
)
from pipeline.generate.draft.prose_synthesis import synthesize_location_significance

# --- location_type_from_signals -------------------------------------------------------------


def test_type_tomb_is_landmark_even_when_ruined() -> None:
    assert location_type_from_signals("Uther's Tomb", "the ruined tomb of the Lightbringer") == "landmark"


def test_type_ruined_keep_resolves_to_ruins() -> None:
    # "Caer" is not an English keep token, so the ruined-evidence signal wins.
    assert location_type_from_signals("Caer Darrow", "the ruined Barov keep on Darrowmere Lake") == "ruins"


def test_type_destroyed_town_resolves_to_ruins() -> None:
    assert location_type_from_signals("Andorhal", "Andorhal was destroyed and now lies in ruins") == "ruins"


def test_type_town_from_seat_of_evidence() -> None:
    assert location_type_from_signals("Hearthglen", "the seat of the regional administration") == "town"


def test_type_natural_feature_from_name() -> None:
    assert location_type_from_signals("Darrowmere River", "a river running south") == "natural_feature"


def test_type_outpost_from_name() -> None:
    assert location_type_from_signals("Felstone Field", "a quiet farmstead") == "outpost"


def test_type_falls_back_to_major_location() -> None:
    assert location_type_from_signals("Mysterious Place", "an indistinct area") == "major_location"


# --- significance synthesis (never the routing enum) ----------------------------------------


def test_significance_offline_is_grounded_not_enum(monkeypatch) -> None:
    monkeypatch.setattr(
        synth, "load_ai_settings", lambda: type("S", (), {"openai_ready": False})()
    )
    out, _ = synthesize_location_significance(
        [{"snippet": "Andorhal was the granary of Lordaeron before the plague struck.", "source_id": "s1"}],
        location_name="Andorhal",
        zone_name="Western Plaguelands",
        location_type="ruins",
    )
    assert out
    assert "major_location_candidate" not in out
    assert out.endswith(".")


def test_significance_template_fallback_when_no_evidence() -> None:
    out, used = synthesize_location_significance(
        [],
        location_name="Andorhal",
        zone_name="Western Plaguelands",
        location_type="ruins",
    )
    assert out == "Andorhal is a notable ruins of Western Plaguelands."
    assert used == []


# --- scorer rebalance -----------------------------------------------------------------------


def _seed(role: str) -> dict[str, object]:
    return {"section_role": role, "snippet": "x", "source_id": "s"}


def _candidate(name: str, mentions: list[dict[str, object]]) -> LocationCandidate:
    cand = LocationCandidate(
        location_id=f"location-{name.lower()}",
        name=name,
        wiki_url="https://warcraft.wiki.gg/wiki/X",
        decision="include",
        seed_mentions=mentions,
        zone_relevant=True,
    )
    return score_location_candidate(cand)


def test_history_prominent_landmark_outscores_repeated_maps_list_farm() -> None:
    farm = _candidate("Felstone Field", [_seed("maps_subregions")] * 3)
    landmark = _candidate("Hearthglen", [_seed("history")] * 3)
    assert landmark.score > farm.score


def test_repeated_same_bucket_mentions_have_diminishing_returns() -> None:
    one = _candidate("A", [_seed("maps_subregions")])
    three = _candidate("B", [_seed("maps_subregions")] * 3)
    # More list entries still help a little, but far less than 3x linear (was 9.0, now 6.0).
    assert three.score < one.score + 2 * 3.0
