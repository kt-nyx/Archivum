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
