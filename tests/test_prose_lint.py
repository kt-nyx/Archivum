from __future__ import annotations

from pipeline.generate.draft.prose_lint import (
    AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
    token_jaccard_overlap,
)


def test_at_a_glance_rejects_dominant_present() -> None:
    text = (
        "Western Plaguelands is a blighted region where the Argent Crusade maintains outposts "
        "and continues to heal the soil while factions clash over Andorhal."
    )
    assert any("dominant present tense" in issue for issue in lint_at_a_glance(text))


def test_at_a_glance_requires_past_or_historical_framing() -> None:
    text = "Western Plaguelands remains a contested frontier between crusaders and undead forces."
    assert any("lacks past-tense" in issue for issue in lint_at_a_glance(text))


def test_at_a_glance_allows_short_present_without_past() -> None:
    text = "A blighted frontier zone."
    assert not lint_at_a_glance(text)


def test_at_a_glance_accepts_past_zone_flavor() -> None:
    text = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm."
    )
    assert not lint_at_a_glance(text)


def test_history_rejects_short_present_body_with_historical_framing() -> None:
    sections = [
        {
            "heading": "Third War",
            "body": "During the Third War the Crusade maintains hold.",
        }
    ]
    assert any("dominant present tense" in issue for issue in lint_history_sections(sections))


def test_history_rejects_maintains_despite_framing() -> None:
    sections = [
        {
            "heading": "Scarlet era",
            "body": (
                "During the Third War, the region fell to the Scourge. The Scarlet Crusade maintains "
                "fortified holdings across the zone and continues to struggle against undead remnants."
            ),
        }
    ]
    assert any("dominant present tense" in issue for issue in lint_history_sections(sections))


def test_history_accepts_clean_past_body() -> None:
    sections = [
        {
            "heading": "Third War",
            "body": (
                "During the Third War, the Scourge under Arthas overran Western Plaguelands, ending "
                "Lordaeron's hold over its farmlands. Villages fell to plague and grain production collapsed."
            ),
        }
    ]
    assert not lint_history_sections(sections)


def test_currently_requires_present_markers() -> None:
    text = (
        "Formerly the grain heartland of the kingdom before the plague arrived years ago during the Third War."
    )
    assert any("present-tense" in issue for issue in lint_currently(text))


def test_currently_accepts_present_zone_flavor() -> None:
    text = (
        "The Argent Crusade and Cenarion Circle work to heal the blighted soil while Horde and Alliance "
        "forces contest control of Andorhal."
    )
    assert not lint_currently(text)


def test_currently_rescue_stub_has_present_tense_markers() -> None:
    stub = (
        "Example Zone remains a contested frontier where crusaders and rival factions "
        "continue to clash over ruined strongholds."
    )
    assert not lint_currently(
        stub,
        zone_name="Example Zone",
        at_a_glance="Once a fertile region that was blighted during the Third War.",
    )


def test_currently_rejects_at_a_glance_overlap() -> None:
    at_a_glance = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm."
    )
    currently = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm and crusaders work to heal them."
    )
    overlap = token_jaccard_overlap(at_a_glance, currently)
    assert overlap >= AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD
    assert any("overlaps at_a_glance" in issue for issue in lint_currently(currently, at_a_glance=at_a_glance))
