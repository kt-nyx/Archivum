from __future__ import annotations

from tests.factories.wiki_first_pages import minimal_instance_page_payload, minimal_zone_page_payload
from tests.test_validation_engine import validate_payload


def test_zone_page_major_factions_provenance_required() -> None:
    payload = minimal_zone_page_payload()
    payload["major_factions"] = [
        {
            "id": "faction-argent-crusade",
            "name": "Argent Crusade",
            "wiki_url": "https://example.test/argent-crusade",
            "summary": (
                "The Argent Crusade maintains patrol routes and defensive operations across "
                "Testlands while coordinating supply lines and regional scouting missions."
            ),
        }
    ]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "provenance.missing_card_pointers"
        and "major_factions" in issue.path
        for issue in report.issues
    )


def test_zone_page_glossary_provenance_required_when_refs_present() -> None:
    payload = minimal_zone_page_payload()
    payload["glossary_refs"] = [
        {
            "term_id": "term-testlands",
            "label": "Testlands",
            "wiki_url": "https://example.test/testlands",
        }
    ]
    report = validate_payload("zone_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "provenance.missing_card_pointers" and "glossary" in issue.path
        for issue in report.issues
    )


def test_instance_page_major_factions_provenance_required() -> None:
    payload = minimal_instance_page_payload()
    payload["major_factions"] = [
        {
            "id": "faction-scourge",
            "name": "Scourge",
            "wiki_url": "https://example.test/scourge",
            "summary": (
                "The Scourge maintains ritual pressure across Test Dungeon while coordinating "
                "recruitment, battlefield reinforcement, and patrol disruption beyond its gates."
            ),
        }
    ]
    report = validate_payload("instance_page", payload)
    assert report.passed is False
    assert any(
        issue.code == "provenance.missing_card_pointers"
        and "major_factions" in issue.path
        for issue in report.issues
    )


def test_linker_writes_glossary_provenance_for_zone_page(tmp_path, monkeypatch) -> None:
    from pipeline.common.run_context import ensure_run_context
    from pipeline.linker.linker import run_glossary_linker

    context = ensure_run_context("run-test-page-glossary", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-testlands.json"
    payload = minimal_zone_page_payload()
    draft_path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda _context=None: [
            {
                "term_id": "term-testlands",
                "alias": "Testlands",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "place",
            }
        ],
    )
    monkeypatch.setattr(
        "pipeline.linker.linker._load_term_metadata",
        lambda _context=None: {
            "term-testlands": {
                "term_id": "term-testlands",
                "label": "Testlands",
                "wiki_url": "https://example.test/testlands",
                "category": "place",
            }
        },
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    draft = __import__("json").loads(draft_path.read_text(encoding="utf-8"))
    assert draft["glossary_refs"]
    assert draft["provenance"]["glossary"]["term-testlands"]
