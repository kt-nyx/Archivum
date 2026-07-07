from __future__ import annotations

import json

from pipeline.generate.draft.claim_routing import apply_claim_views_to_evidence_rows
from pipeline.generate.draft.pages import build_zone_page
from pipeline.generate.draft.prose_lint import (
    MAX_AT_A_GLANCE_WORDS,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
    word_count,
)
from tests.factories.wiki_first_pages import stamp_canonical_evidence_ids


def _fact_pack(zone_id: str) -> dict[str, object]:
    return {
        "entity_id": zone_id,
        "name": "Example Zone",
        "source_ids": ["src-zone"],
        "revision_ids": ["mw:1"],
        "source_urls": {"src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone"},
    }


def _prose_evidence_rows(zone_id: str) -> list[dict[str, object]]:
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
            "build_meta": {
                "source_id": "src-zone",
                "subject_zone_id": zone_id,
                "section_role": "lead",
            },
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
            "build_meta": {
                "source_id": "src-zone",
                "subject_zone_id": zone_id,
                "section_role": "cataclysm_edit",
            },
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
                        "broken keeps, and scattered villages throughout the zone. The farmlands burned "
                        "first, and the survivors who fled carried plague stories to every neighboring "
                        "province."
                    ),
                    "section_role": "history",
                },
                {
                    "snippet": (
                        "Crusader expeditions established fortified outposts and slowly reclaimed "
                        "key strongholds from the lingering scourge that had dominated the region for "
                        "many years after the initial collapse. Their engineers rebuilt the watchtowers "
                        "along the old roads, and patrols escorted supply caravans between the recovered "
                        "garrisons."
                    ),
                    "section_role": "history",
                    "raw_section_role": "third_war_edit",
                },
                {
                    "snippet": (
                        "After the Cataclysm, recovery efforts reshaped roads and outposts while "
                        "undead remnants were pushed back along the frontier between crusaders and "
                        "broken keeps across the ruined farmland. The wardens who returned planted new "
                        "groves beside the rebuilt bridges, and traders followed once the roads were "
                        "declared safe."
                    ),
                    "section_role": "cataclysm_edit",
                },
            ],
            "build_meta": {
                "source_id": "src-zone",
                "subject_zone_id": zone_id,
                "section_role": "history",
            },
        },
    ]


def _prose_evidence(zone_id: str) -> list[dict[str, object]]:
    # Slice 7: hand-built rows must carry paragraph identity (see stamp helper).
    return stamp_canonical_evidence_ids(_prose_evidence_rows(zone_id))


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
    assert not lint_currently(
        str(draft["currently"]),
        zone_name="Example Zone",
        at_a_glance=str(draft["at_a_glance"]),
    )
    assert not lint_history_sections(draft["history_sections"], max_sections=8)


def test_zone_draft_excludes_internal_claim_metadata(monkeypatch) -> None:
    """Slice 11 schema contract: claim-level metadata stays internal, never in public draft JSON.

    Build a zone page from evidence that carries claim views, then assert the serialized draft has
    no internal claim keys (``_claim_views``, ``is_claim_view``, ``claim_id``) anywhere.
    """
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    history_excerpt = (
        "The region was devastated during the invasion and fell under undead control for decades "
        "before military campaigns began restoring order across the frontier and broken keeps."
    )
    evidence = _prose_evidence(zone_id)
    for row in evidence:
        for item in row["evidence_items"]:
            item["canonical_evidence_id"] = "canonical-hist"
    claim_temporal_decisions = [
        {
            "canonical_evidence_id": "canonical-hist",
            "source_id": "src-zone",
            "source_title": "Example Zone",
            "source_excerpt": history_excerpt,
            "claims": [
                {
                    "canonical_evidence_id": "canonical-hist",
                    "claim_id": "claim-restore",
                    "claim_text": (
                        "Military campaigns restored order across the frontier and broken keeps."
                    ),
                    "claim_type": "event",
                    "temporal_scope": "pre_entry_history",
                    "history_eligibility": "history_background",
                    "spoiler_safety": "safe_background",
                    "source_excerpt": history_excerpt,
                }
            ],
        }
    ]
    routed = apply_claim_views_to_evidence_rows(evidence, claim_temporal_decisions)

    draft = build_zone_page(_fact_pack(zone_id), routed, [], [], [], {}, {}, None)

    # ``section_coverage_decisions`` is an internal sidecar: draft_writer pops it out of the page
    # and writes it to data/decisions/ before the public draft is serialized (it intentionally
    # carries claim-level ``claim_ids``). Mirror that extraction so this guard checks the actual
    # public draft shape, not the pre-extraction page entity.
    public_draft = {k: v for k, v in draft.items() if k != "section_coverage_decisions"}

    serialized = json.dumps(public_draft)
    assert "_claim_views" not in serialized
    assert "is_claim_view" not in serialized
    assert "claim_id" not in serialized


def test_build_zone_page_prefers_present_snippet_for_at_a_glance(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "source_id": "src-past",
                    "snippet": (
                        "Once a fertile frontier, the region was devastated during the Third War and remained "
                        "blighted for decades before recovery efforts began."
                    ),
                    "section_role": "history",
                },
                {
                    "source_id": "src-present",
                    "snippet": (
                        "Example Zone is a blighted region where crusaders maintain outposts and continue "
                        "to heal the soil while factions clash over strategic ruins."
                    ),
                    "section_role": "lead",
                },
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "source_id": "src-current",
                    "snippet": (
                        "Crusaders continue to push back undead forces while recovery efforts reshape "
                        "roads and outposts across the frontier."
                    ),
                    "section_role": "cataclysm_edit",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
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
    assert "is" in draft["at_a_glance"] or "maintain" in draft["at_a_glance"]
    assert not lint_at_a_glance(str(draft["at_a_glance"]), zone_name="Example Zone")


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
