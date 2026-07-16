"""S3 retail/Classic crawl filter: shared helpers + integration seams (offline)."""

from __future__ import annotations

import json

import pytest

from pipeline.common import retail
from pipeline.discovery.instance_bosses import BossCandidate, prefilter_character_pool
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


def test_prefilter_character_pool_applies_explicit_exclusion_set() -> None:
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
        pool, instance_name="Example Vault", excluded_normalized_names={"ravenian"}
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


def test_participant_evidence_records_separate_kind_presence_and_retail_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = {
        "entity_id": "instance-example-vault",
        "entity_type": "instance",
        "name": "Example Vault",
        "source_id": "src-example-vault",
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
                "ravenian": ["Example bosses", "Removed creatures", "Characters"],
                "darkmaster gandling": ["Example bosses", "Characters"],
        }

    monkeypatch.setattr(traverse_wiki, "fetch_categories_for_titles", fake_categories)
    report: list[dict[str, object]] = []
    decisions = {}
    traverse_wiki._record_instance_participant_evidence([instance], report, decisions)
    records = {row["candidate_name"]: row for row in instance["instance_participant_evidence"]}
    assert records["Ravenian"]["retail_scope"] == "non_retail"
    assert records["Darkmaster Gandling"]["retail_scope"] == "retail_confirmed"
    assert records["Darkmaster Gandling"]["entity_kind"] == "named_actor"
    assert records["Darkmaster Gandling"]["instance_presence_evidence"]
    assert any(row["status"] == "instance_participant_evidence_recorded" for row in report)


def test_participant_evidence_no_instances_is_noop() -> None:
    report: list[dict[str, object]] = []
    traverse_wiki._record_instance_participant_evidence([{"entity_type": "zone"}], report, {})
    assert report == []


def test_participant_evidence_marks_category_fetch_failure_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = {
        "entity_type": "instance", "name": "Example", "auxiliary_role": "",
        "section_blocks": [{"section_role": "bosses", "text": '<a href="/wiki/Example_Boss">Example Boss</a>'}],
        "structured_links": [{"href": "/wiki/Example_Boss", "section_role": "bosses", "label": "Example Boss"}],
    }
    monkeypatch.setattr(traverse_wiki, "fetch_categories_for_titles", lambda _titles: (_ for _ in ()).throw(RuntimeError("offline")))
    traverse_wiki._record_instance_participant_evidence([instance], [], {})
    assert instance["instance_participant_evidence"][0]["retail_scope"] == "unknown"
