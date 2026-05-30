from __future__ import annotations

from pipeline.discovery.geography import resolve_parent_continent, title_to_slug


def test_title_to_slug() -> None:
    assert title_to_slug("Eastern Kingdoms") == "eastern-kingdoms"


def test_resolve_parent_continent_from_currently_input() -> None:
    evidence_rows = [
        {
            "field_name": "currently_input",
            "build_meta": {"source_kind": "seed"},
            "evidence_items": [
                {"snippet": "Patrols across Kalimdor continue to secure trade routes and outposts."}
            ],
        }
    ]
    assert resolve_parent_continent(evidence_rows) == "kalimdor"


def test_resolve_parent_continent_from_seed_history() -> None:
    evidence_rows = [
        {
            "field_name": "history_digest",
            "build_meta": {"source_kind": "seed"},
            "evidence_items": [
                {
                    "snippet": (
                        "During the Third War, Lordaeron and the Eastern Kingdoms suffered "
                        "catastrophic plague-era devastation."
                    )
                }
            ],
        }
    ]
    assert resolve_parent_continent(evidence_rows) == "eastern-kingdoms"


def test_resolve_parent_continent_ignores_simile_northrend_in_history() -> None:
    evidence_rows = [
        {
            "field_name": "at_a_glance_input",
            "build_meta": {"source_kind": "seed"},
            "evidence_items": [
                {"snippet": "The Western Plaguelands are located in northern Lordaeron."},
                {
                    "snippet": (
                        "Just as in Northrend, the citizens who contracted the plague died "
                        "and arose as the Lich King's willing slaves."
                    )
                },
            ],
        },
        {
            "field_name": "history_digest",
            "build_meta": {"source_kind": "seed"},
            "evidence_items": [
                {"snippet": "Just as in Northrend, the cold preserved the dead across the frontier."}
            ],
        },
    ]
    assert resolve_parent_continent(evidence_rows) == "eastern-kingdoms"


def test_resolve_parent_continent_prefers_geography_input() -> None:
    evidence_rows = [
        {
            "field_name": "geography_input",
            "build_meta": {"source_kind": "seed"},
            "evidence_items": [
                {
                    "snippet": (
                        "Western Plaguelands is a zone in north-central Lordaeron on the Eastern Kingdoms."
                    )
                }
            ],
        }
    ]
    assert resolve_parent_continent(evidence_rows) == "eastern-kingdoms"


def test_resolve_parent_continent_maps_lordaeron_only_to_eastern_kingdoms() -> None:
    evidence_rows = [
        {
            "field_name": "at_a_glance_input",
            "build_meta": {"source_kind": "seed"},
            "evidence_items": [{"snippet": "The zone spans northern Lordaeron between key crusader holdings."}],
        }
    ]
    assert resolve_parent_continent(evidence_rows) == "eastern-kingdoms"
