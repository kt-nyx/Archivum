import json
from pathlib import Path

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.linker.linker import run_glossary_linker


def test_linker_adds_glossary_links_and_zone_provenance(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-linker-provenance", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-western-plaguelands.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-western-plaguelands",
                    "at_a_glance": (
                        "The Scourge continues to pressure regional defenses across contested "
                        "farmland routes and fortified recovery lines."
                    ),
                    "currently": (
                        "Commanders coordinate prolonged anti-Scourge operations while escort "
                        "teams secure supply roads and evacuation corridors."
                    ),
                    "history": (
                        "The Western Plaguelands endured repeated plague campaigns, military "
                        "counteroffensives, and post-war stabilization cycles."
                    ),
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-wpl",
                        "url": "https://example.test/wpl",
                        "revision_id": "mw:123",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-wpl",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:123",
                            "excerpt_hash": "sha1:1111111111111111",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    output_path = run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    report = json.loads(output_path.read_text(encoding="utf-8"))
    updated_draft = json.loads(draft_path.read_text(encoding="utf-8"))

    assert report["linked_terms"]
    linked_term_ids = [link["term_id"] for link in updated_draft["glossary"]]
    assert linked_term_ids
    for term_id in linked_term_ids:
        assert term_id in updated_draft["provenance"]["glossary"]
        assert updated_draft["provenance"]["glossary"][term_id]


def test_linker_routes_ambiguous_alias_to_manual_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-linker-ambiguity", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-ambiguous.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-ambiguous",
                "at_a_glance": "Commanders discuss the Front across multiple theaters.",
                "currently": "",
                "history": "",
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-front",
                        "url": "https://example.test/front",
                        "revision_id": "mw:789",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-front",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:789",
                            "excerpt_hash": "sha1:3333333333333333",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda: [
            {
                "term_id": "term-front-one",
                "alias": "front",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "place",
            },
            {
                "term_id": "term-front-two",
                "alias": "front",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
        ],
    )

    output_path = run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    report = json.loads(output_path.read_text(encoding="utf-8"))
    updated_draft = json.loads(draft_path.read_text(encoding="utf-8"))

    assert updated_draft["glossary"] == []
    assert any(
        row["reason"] == "ambiguous alias candidates require disambiguation"
        for row in report["manual_review_candidates"]
    )


def test_linker_routes_review_band_confidence_to_manual_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-linker-review-band", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-review-band.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-review-band",
                "at_a_glance": "Commanders discuss campaign front dynamics.",
                "currently": "",
                "history": "",
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-front",
                        "url": "https://example.test/front",
                        "revision_id": "mw:789",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-front",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:789",
                            "excerpt_hash": "sha1:3333333333333333",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda: [
            {
                "term_id": "term-campaign-front",
                "alias": "campaign front",
                "alias_type": "fuzzy",
                "case_rule": "insensitive",
                "category": "event",
            }
        ],
    )

    output_path = run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    report = json.loads(output_path.read_text(encoding="utf-8"))
    updated_draft = json.loads(draft_path.read_text(encoding="utf-8"))

    assert updated_draft["glossary"] == []
    assert any(
        row["reason"] == "confidence in review band" for row in report["manual_review_candidates"]
    )


def test_linker_prefers_section_pointer_for_new_glossary_provenance(tmp_path: Path) -> None:
    context = ensure_run_context(
        "run-test-linker-section-pointer",
        artifacts_root=tmp_path / "runs",
    )
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-section-pointer.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-section-pointer",
                "at_a_glance": "Brief overview text.",
                "currently": "Scourge forces pressure defensive lines across the front.",
                "history": "Historical summary remains brief.",
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-currently",
                        "url": "https://example.test/currently",
                        "revision_id": "mw:789",
                    }
                ],
                "provenance": {
                    "at_a_glance": [],
                    "currently": [
                        {
                            "source_id": "src-currently",
                            "locator": "section:currently paragraph:1",
                            "revision_id": "mw:789",
                            "excerpt_hash": "sha1:9999999999999999",
                        }
                    ],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    updated_draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if not updated_draft["glossary"]:
        pytest.skip("no glossary term auto-linked in this run")
    first_term = updated_draft["glossary"][0]["term_id"]
    pointer = updated_draft["provenance"]["glossary"][first_term][0]
    assert pointer["locator"] == "section:currently paragraph:1"


def test_linker_enforces_density_cap_on_final_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-linker-density-cap", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-density-cap.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-density-cap",
                "at_a_glance": (
                    "Alpha staging coordinates patrol lanes while Beta command maintains route "
                    "control across the district under repeated pressure and sustained alerts."
                ),
                "currently": (
                    "Gamma detachments reinforce corridor defenses as Delta teams stabilize "
                    "supply flow, monitor threat movement, and rotate unit coverage."
                ),
                "history": (
                    "Epsilon campaign cycles repeatedly tested logistics continuity and command "
                    "resilience while local forces recovered critical infrastructure."
                ),
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-cap",
                        "url": "https://example.test/cap",
                        "revision_id": "mw:501",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-cap",
                            "locator": "section:at_a_glance paragraph:1",
                            "revision_id": "mw:501",
                            "excerpt_hash": "sha1:aaaa501aaaa501a",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda: [
            {
                "term_id": "term-alpha",
                "alias": "alpha",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-beta",
                "alias": "beta",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-gamma",
                "alias": "gamma",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-delta",
                "alias": "delta",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-epsilon",
                "alias": "epsilon",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
        ],
    )
    report_path = run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    words = len(
        (
            f"{updated.get('at_a_glance', '')} "
            f"{updated.get('currently', '')} "
            f"{updated.get('history', '')}"
        ).split()
    )
    assert words > 0
    density = (len(updated["glossary"]) * 100.0) / words
    assert density <= 4.0
    assert any(
        row.get("reason") == "link density cap enforced"
        for row in report["manual_review_candidates"]
    )


def test_linker_short_drafts_do_not_exceed_density_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-linker-short-density", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-short-density.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-short-density",
                "at_a_glance": "Front patrols hold lines.",
                "currently": "Front signals continue.",
                "history": "",
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-short",
                        "url": "https://example.test/short",
                        "revision_id": "mw:511",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-short",
                            "locator": "section:at_a_glance paragraph:1",
                            "revision_id": "mw:511",
                            "excerpt_hash": "sha1:aaaa511aaaa511a",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda: [
            {
                "term_id": "term-front",
                "alias": "front",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            }
        ],
    )
    report_path = run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    words = len(
        (
            f"{updated.get('at_a_glance', '')} "
            f"{updated.get('currently', '')} "
            f"{updated.get('history', '')}"
        ).split()
    )
    assert words < 25
    assert len(updated["glossary"]) == 0
    assert any(
        row.get("reason") == "link density cap enforced"
        for row in report["manual_review_candidates"]
    )


def test_linker_ambiguity_is_evaluated_per_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-linker-per-section", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "zone"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-per-section.json"
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-per-section",
                "at_a_glance": "Commanders coordinate the Front.",
                "currently": "The Front remains unstable.",
                "history": "Historical Front campaigns continue to influence strategy.",
                "glossary": [],
                "sources": [
                    {
                        "source_id": "src-front-sections",
                        "url": "https://example.test/front-sections",
                        "revision_id": "mw:610",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-front-sections",
                            "locator": "section:at_a_glance paragraph:1",
                            "revision_id": "mw:610",
                            "excerpt_hash": "sha1:bbbb610bbbb610b",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda: [
            {
                "term_id": "term-front-one",
                "alias": "front",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "place",
            },
            {
                "term_id": "term-front-two",
                "alias": "front",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
        ],
    )
    report_path = run_glossary_linker(context, [draft_path], max_entity_concurrency=2)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ambiguous_rows = [
        row
        for row in report["manual_review_candidates"]
        if row.get("reason") == "ambiguous alias candidates require disambiguation"
    ]
    assert len(ambiguous_rows) >= 2
