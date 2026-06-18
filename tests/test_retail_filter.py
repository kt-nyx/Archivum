"""S3 retail/Classic crawl filter: shared helpers + integration seams (offline)."""

from __future__ import annotations

import json

import pytest

from pipeline.common import retail
from pipeline.discovery.instance_bosses import (
    BossCandidate,
    prefilter_character_pool,
    should_reject_boss_title,
)
from pipeline.discovery.workflow import _classify_retail_eligibility
from pipeline.ingest import fetch_wiki, traverse_wiki


def test_is_classic_categorized_matches_markers() -> None:
    assert retail.is_classic_categorized(["Scholomance bosses", "Removed creatures"])
    assert retail.is_classic_categorized(["Classic dungeons"])
    assert retail.is_classic_categorized(["Warcraft III units"])
    assert not retail.is_classic_categorized(["Dungeons", "Mists of Pandaria"])
    assert not retail.is_classic_categorized([])
    assert not retail.is_classic_categorized(None)


def test_is_non_retail_title_parenthetical() -> None:
    assert retail.is_non_retail_title("Scholomance (Classic)")
    assert retail.is_non_retail_title("Deadmines (Burning Crusade)")
    assert not retail.is_non_retail_title("Ravenian")
    assert not retail.is_non_retail_title("Darkmaster Gandling")


def test_known_classic_entity_backstop() -> None:
    assert retail.is_known_classic_entity("Lord Alexei Barov")
    assert retail.is_known_classic_entity("ravenian")
    assert not retail.is_known_classic_entity("Darkmaster Gandling")


def test_should_reject_boss_title_drops_classic_parenthetical() -> None:
    assert should_reject_boss_title("Scholomance (Classic)")
    # Clean-href Classic NPCs are NOT rejected here (handled by the exclusion set), so the
    # structural filter stays general and never hardcodes named entities.
    assert not should_reject_boss_title("Ravenian")
    assert not should_reject_boss_title("Lord Alexei Barov")


def test_prefilter_character_pool_applies_exclusion_set() -> None:
    pool = [
        BossCandidate(
            boss_id="character-ravenian",
            name="Ravenian",
            wiki_url="",
            source_section_role="denizens",
        ),
        BossCandidate(
            boss_id="character-gandling",
            name="Darkmaster Gandling",
            wiki_url="",
            source_section_role="bosses",
        ),
    ]
    filtered = prefilter_character_pool(
        pool, instance_name="Scholomance", excluded_normalized_names={"ravenian"}
    )
    assert [c.name for c in filtered] == ["Darkmaster Gandling"]


def test_classify_retail_eligibility_uses_categories() -> None:
    assert _classify_retail_eligibility("plain retail body", ["Dungeons"]) == "eligible"
    assert (
        _classify_retail_eligibility("plain retail body", ["Classic dungeons"])
        == "ineligible_classic_only"
    )
    # Body fallback still works when no categories are supplied.
    assert _classify_retail_eligibility("This is classic only content") == "ineligible_classic_only"


def _fake_query_response() -> str:
    return json.dumps(
        {
            "query": {
                "normalized": [{"from": "ravenian", "to": "Ravenian"}],
                "redirects": [{"from": "The Ravenian", "to": "Ravenian"}],
                "pages": [
                    {
                        "title": "Ravenian",
                        "categories": [
                            {"title": "Category:Scholomance bosses"},
                            {"title": "Category:Removed creatures"},
                        ],
                    },
                    {
                        "title": "Darkmaster Gandling",
                        "categories": [{"title": "Category:Scholomance bosses"}],
                    },
                ],
            }
        }
    )


def test_fetch_categories_for_titles_resolves_and_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_get_text(url: str, **kwargs: object) -> str:
        captured["url"] = url
        return _fake_query_response()

    monkeypatch.setattr("pipeline.common.http.get_text", fake_get_text)
    result = fetch_wiki.fetch_categories_for_titles(["Ravenian", "Darkmaster Gandling"])
    assert "prop=categories" in captured["url"]
    assert result["ravenian"] == ["Scholomance bosses", "Removed creatures"]
    assert result["darkmaster gandling"] == ["Scholomance bosses"]
    assert retail.is_classic_categorized(result["ravenian"])
    assert not retail.is_classic_categorized(result["darkmaster gandling"])


def test_exclude_classic_instance_characters_tags_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = {
        "entity_id": "instance-scholomance",
        "entity_type": "instance",
        "name": "Scholomance",
        "auxiliary_role": "",
        "section_blocks": [
            {
                "section_role": "denizens",
                "text": 'See <a href="/wiki/Ravenian">Ravenian</a> and '
                '<a href="/wiki/Darkmaster_Gandling">Darkmaster Gandling</a>.',
            }
        ],
        "structured_links": [
            {"href": "/wiki/Ravenian", "section_role": "denizens", "label": "Ravenian"},
            {
                "href": "/wiki/Darkmaster_Gandling",
                "section_role": "bosses",
                "label": "Darkmaster Gandling",
            },
        ],
    }

    def fake_categories(titles: object, **kwargs: object) -> dict[str, list[str]]:
        return {
            "ravenian": ["Scholomance bosses", "Removed creatures"],
            "darkmaster gandling": ["Scholomance bosses"],
        }

    monkeypatch.setattr(traverse_wiki, "fetch_categories_for_titles", fake_categories)
    report: list[dict[str, object]] = []
    traverse_wiki._exclude_classic_instance_characters([instance], report)
    assert instance["classic_excluded_characters"] == ["ravenian"]
    assert any(row["status"] == "excluded_classic" for row in report)


def test_exclude_classic_instance_characters_no_instances_is_noop() -> None:
    report: list[dict[str, object]] = []
    traverse_wiki._exclude_classic_instance_characters([{"entity_type": "zone"}], report)
    assert report == []
