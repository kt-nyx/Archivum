from __future__ import annotations

import os

from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
    word_count,
)
from pipeline.generate.draft.wiki_first import build_zone_page


def _fact_pack(zone_id: str) -> dict[str, object]:
    return {
        "entity_id": zone_id,
        "name": "Example Zone",
        "source_ids": ["src-zone"],
        "revision_ids": ["mw:1"],
        "source_urls": {"src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone"},
    }


def _prose_evidence(zone_id: str) -> list[dict[str, object]]:
    return [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": (
                        "A contested frontier where crusaders and druids resist undead remnants "
                        "across ruined farmland and broken keeps."
                    ),
                    "section_role": "lead",
                },
                {
                    "snippet": (
                        "The zone was devastated during the Third War and remained blighted for decades "
                        "before recovery efforts began reshaping the roads."
                    ),
                    "section_role": "history",
                },
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id, "section_role": "lead"},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "snippet": (
                        "Recovery efforts after the Cataclysm continue to reshape roads and outposts "
                        "while crusaders and druids push back undead forces along the main road."
                    ),
                    "section_role": "cataclysm_edit",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id, "section_role": "cataclysm_edit"},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "snippet": (
                        "The region was devastated during the invasion and fell under undead control "
                        "for decades before military campaigns began restoring order across the frontier, "
                        "broken keeps, and scattered villages throughout the zone."
                    ),
                    "section_role": "history",
                },
                {
                    "snippet": (
                        "Crusader expeditions established fortified outposts and slowly reclaimed "
                        "key strongholds from the lingering scourge that had dominated the region for "
                        "many years after the initial collapse."
                    ),
                    "section_role": "history_third_war",
                },
                {
                    "snippet": (
                        "After the Cataclysm, recovery efforts reshaped roads and outposts while "
                        "undead remnants were pushed back along the frontier between crusaders and "
                        "broken keeps across the ruined farmland."
                    ),
                    "section_role": "cataclysm_edit",
                },
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id, "section_role": "history"},
        },
    ]


def test_build_zone_page_prose_passes_lint_without_llm(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    draft = build_zone_page(
        _fact_pack(zone_id),
        _prose_evidence(zone_id),
        [],
        [],
        [],
        {},
        {},
        None,
    )
    assert draft["at_a_glance"]
    assert draft["currently"]
    assert len(draft["history_sections"]) >= 3
    assert word_count(str(draft["at_a_glance"])) <= MAX_AT_A_GLANCE_WORDS
    assert not lint_at_a_glance(str(draft["at_a_glance"]), zone_name="Example Zone")
    assert not lint_currently(str(draft["currently"]), zone_name="Example Zone")
    assert not lint_history_sections(draft["history_sections"], max_sections=8)


def test_build_zone_page_prefers_expansion_edit_for_currently(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence = _prose_evidence(zone_id)
    evidence[1]["evidence_items"] = [
        {
            "snippet": "Formerly the grain heartland before the plague arrived years ago.",
            "section_role": "quests",
        },
        {
            "snippet": (
                "Recovery efforts after the Cataclysm continue to reshape roads and outposts "
                "while crusaders push back undead forces."
            ),
            "section_role": "cataclysm_edit",
        },
    ]
    draft = build_zone_page(
        _fact_pack(zone_id),
        evidence,
        [],
        [],
        [],
        {},
        {},
        None,
    )
    assert "Cataclysm" in draft["currently"] or "recovery" in draft["currently"].lower()


def test_build_zone_page_rescue_path_trims_at_a_glance(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": " ".join(["frontier"] * 80),
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        }
    ]
    draft = build_zone_page(
        _fact_pack(zone_id),
        evidence,
        [],
        [],
        [],
        {},
        {},
        None,
    )
    assert word_count(str(draft["at_a_glance"])) <= MAX_AT_A_GLANCE_WORDS
    assert not lint_at_a_glance(str(draft["at_a_glance"]), zone_name="Example Zone")


def test_build_zone_page_history_headings_are_role_based(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    draft = build_zone_page(
        _fact_pack(zone_id),
        _prose_evidence(zone_id),
        [],
        [],
        [],
        {},
        {},
        None,
    )
    headings = [section["heading"] for section in draft["history_sections"]]
    assert "History 1" not in headings
    assert any("History" in heading or "Cataclysm" in heading for heading in headings)
