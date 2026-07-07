from __future__ import annotations

import pipeline.generate.draft.prose_synthesis as synth
from pipeline.generate.draft.location_scoring import (
    LocationCandidate,
    location_significance_from_signals,
    location_type_from_signals,
    score_location_candidate,
)
from pipeline.generate.draft.pages.cards import _build_location_card_body
from pipeline.generate.draft.prose_synthesis import synthesize_location_significance

# --- location_type_from_signals: structured-signal precedence (Slice 10) ---------------------
# Precedence is wiki categories -> infobox type -> LLM enum -> major_location default. No
# name/evidence-text keyword ladders remain.


def test_type_category_is_authoritative_and_first_match_wins() -> None:
    # Andorhal is co-tagged Cities + Destroyed settlements; the destruction category wins.
    assert location_type_from_signals(["Cities", "Destroyed settlements"]) == "ruins"
    assert location_type_from_signals(["Towns"]) == "town"
    assert location_type_from_signals(["Villages"]) == "town"


def test_type_category_wins_over_llm_enum() -> None:
    # An authoritative category is never overridden by the model's own classification.
    assert location_type_from_signals(["Towns"], llm_type="ruins") == "town"


def test_type_infobox_used_when_no_category() -> None:
    assert location_type_from_signals([], infobox={"type": "fortress"}) == "fortress"
    # A category still beats the infobox.
    assert location_type_from_signals(["Towns"], infobox={"type": "fortress"}) == "town"


def test_type_infobox_matches_wiki_cased_labels() -> None:
    # Slice 12: parse_infobox preserves the wiki's own label casing ("Type"), so the
    # infobox step must match keys case-insensitively or it silently never fires.
    assert location_type_from_signals([], infobox={"Type": "Fortress"}) == "fortress"
    assert (
        location_type_from_signals([], infobox={"_title": "Caer Darrow", "Type": "Town"}) == "town"
    )


def test_type_llm_enum_used_when_no_category_or_infobox() -> None:
    assert location_type_from_signals([], llm_type="landmark") == "landmark"


def test_type_invalid_llm_enum_falls_back_to_default() -> None:
    assert location_type_from_signals([], llm_type="not_a_type") == "major_location"


def test_type_falls_back_to_major_location() -> None:
    assert location_type_from_signals([]) == "major_location"


# --- location_significance_from_signals: no category rule, LLM enum -> default ---------------


def test_significance_llm_enum_used_and_invalid_ignored() -> None:
    assert location_significance_from_signals(llm_tag="sacred_landmark") == "sacred_landmark"
    assert location_significance_from_signals(llm_tag="not_a_tag") == "major_location"
    assert location_significance_from_signals() == "major_location"


# --- card body: LLM enum rides through, categories still win (Slice 10) ----------------------


def _card_candidate(name: str, categories: list[str]) -> LocationCandidate:
    return LocationCandidate(
        location_id=f"location-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url=f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
        categories=categories,
    )


def test_card_uthers_tomb_is_sacred_landmark_never_battlefield() -> None:
    # Tomb evidence that mentions a war: the retired keyword ladder read "war" as a battlefield.
    # With the LLM enum riding the summary call, the model's sacred_landmark verdict is published.
    candidate = _card_candidate("Uther's Tomb", categories=[])
    card = _build_location_card_body(
        candidate,
        summary="Uther's Tomb honors the fallen Lightbringer near the war-scarred fields.",
        reason_codes=["include"],
        llm_location_type="landmark",
        llm_significance_tag="sacred_landmark",
    )
    assert card is not None
    assert card["significance_tag"] == "sacred_landmark"
    assert card["significance_tag"] != "battlefield"
    assert card["location_type"] == "landmark"


def test_card_category_rule_still_wins_over_llm() -> None:
    candidate = _card_candidate("Andorhal", categories=["Cities", "Destroyed settlements"])
    card = _build_location_card_body(
        candidate,
        summary="Andorhal lies in ruins after the plague consumed the granary of Lordaeron.",
        reason_codes=["include"],
        llm_location_type="city",
        llm_significance_tag="settlement_hub",
    )
    assert card is not None
    assert card["location_type"] == "ruins"  # category beats the LLM's "city"


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


def _lore_candidate(name: str, *, lore: bool, seed: bool = True) -> LocationCandidate:
    cand = LocationCandidate(
        location_id=f"location-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url="https://warcraft.wiki.gg/wiki/X",
        decision="include",
        zone_relevant=True,
        lore_significant=lore,
        seed_mentions=[{"section_role": "maps_subregions", "snippet": name, "source_id": "s"}]
        if seed
        else [],
    )
    return cand


def test_lore_significant_landmarks_displace_maps_only_farms() -> None:
    from pipeline.generate.draft.location_scoring import select_location_cards

    candidates = [
        _lore_candidate("Andorhal", lore=True),
        _lore_candidate("Hearthglen", lore=True),
        _lore_candidate("Caer Darrow", lore=True),
        _lore_candidate("Felstone Field", lore=False),
        _lore_candidate("Dalson's Farm", lore=False),
        _lore_candidate("Darrowmere Lake", lore=False),
    ]
    selected = {c.name for c in select_location_cards(candidates)}
    assert selected == {"Andorhal", "Hearthglen", "Caer Darrow"}


def test_lore_gate_inactive_when_too_few_lore_landmarks() -> None:
    # With fewer than MIN_LOCATION_CARDS lore landmarks, fall back to normal scoring (so sparse
    # zones still surface their maps-listed places).
    from pipeline.generate.draft.location_scoring import select_location_cards

    candidates = [
        _lore_candidate("Andorhal", lore=True),
        _lore_candidate("Felstone Field", lore=False),
        _lore_candidate("Charred Outpost", lore=False),
    ]
    selected = {c.name for c in select_location_cards(candidates)}
    assert "Felstone Field" in selected  # gate inactive, farms still eligible


def test_history_prominent_landmark_outscores_repeated_maps_list_farm() -> None:
    farm = _candidate("Felstone Field", [_seed("maps_subregions")] * 3)
    landmark = _candidate("Hearthglen", [_seed("history")] * 3)
    assert landmark.score > farm.score


def test_repeated_same_bucket_mentions_have_diminishing_returns() -> None:
    one = _candidate("A", [_seed("maps_subregions")])
    three = _candidate("B", [_seed("maps_subregions")] * 3)
    # More list entries still help a little, but far less than 3x linear (was 9.0, now 6.0).
    assert three.score < one.score + 2 * 3.0
