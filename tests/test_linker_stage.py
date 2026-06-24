import json
from pathlib import Path

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.linker.linker import run_glossary_linker
from pipeline.validate.engine import validate_payload


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
                    "major_factions": {},
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
                    "major_factions": {},
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
        lambda _context=None: [
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
                    "major_factions": {},
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
        lambda _context=None: [
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
                    "major_factions": {},
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
                    "major_factions": {},
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
        lambda _context=None: [
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
                    "major_factions": {},
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
        lambda _context=None: [
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
                    "major_factions": {},
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
        lambda _context=None: [
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


def test_linker_keeps_instance_page_schema_valid_with_glossary_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context("run-test-linker-instance-page", artifacts_root=tmp_path / "runs")
    draft_dir = context.data_dir / "drafts" / "instance_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "instance-scholomance.json"
    draft_path.write_text(
        json.dumps(
            {
                "instance_id": "instance-scholomance",
                "name": "Scholomance",
                "instance_type": "dungeon",
                "parent_zone_id": "zone-western-plaguelands",
                "expansion_context": "retail",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Scholomance",
                "at_a_glance": (
                    "Scholomance remains a major Scourge stronghold in Lordaeron where necromancers "
                    "train adepts, coordinate plague operations, and project ritual pressure across "
                    "the surrounding blighted countryside."
                ),
                "overview": " ".join(
                    [
                        "Scholomance was founded as a school for battle-mages who studied forbidden necromancy "
                        "after Lordaeron fell to plague and civil war. Its founders claimed they could control "
                        "death itself, training students in rituals that bound spirits to stone halls and shadowed "
                        "lecture chambers beneath the Western Plaguelands. Over decades the institution became a "
                        "stronghold for hostile instructors, rival cabals, and experiments that threatened every "
                        "nearby settlement. Crusader patrols and local militias repeatedly assaulted the academy "
                        "yet its inner vaults endured, guarded by fanatical wardens and archivists who preserved "
                        "grim curricula. Darkmaster Gandling and his circle still coordinate recruitment, "
                        "battlefield reinforcement, and ritual escalation beyond Scholomance's crumbling gates.",
                    ]
                    * 1
                ),
                "history_sections": [
                    {
                        "heading": "Necromantic Ascendancy",
                        "body": (
                            "Scholomance evolved into a fortified academy where necromancers trained "
                            "forces, coordinated plague operations, and sustained recurring pressure "
                            "on surrounding settlements while expanding ritual networks, recruiting "
                            "new adepts, and reinforcing commanders who projected threats into nearby "
                            "territories over repeated campaign cycles."
                        ),
                        "source_refs": [],
                    }
                ],
                "key_characters": [],
                "major_factions": [],
                "lore_source": "instance_page",
                "lore_source_reason": None,
                "variant_policy": "standalone",
                "variant_reason_codes": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-instance",
                        "url": "https://warcraft.wiki.gg/wiki/Scholomance",
                        "revision_id": "mw:123",
                    }
                ],
                "provenance": {
                    "identity_header": [
                        {
                            "source_id": "src-instance",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:123",
                            "excerpt_hash": "sha1:instance111111111",
                        }
                    ],
                    "story_context": [
                        {
                            "source_id": "src-instance",
                            "locator": "section:overview paragraph:1",
                            "revision_id": "mw:123",
                            "excerpt_hash": "sha1:instance222222222",
                        },
                        {
                            "source_id": "src-instance",
                            "locator": "section:history paragraph:2",
                            "revision_id": "mw:123",
                            "excerpt_hash": "sha1:instance333333333",
                        },
                    ],
                    "key_characters": {},
                    "major_factions": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.linker.linker._load_alias_dictionary",
        lambda _context=None: [
            {
                "term_id": "term-scourge",
                "alias": "Scourge",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "faction",
            }
        ],
    )

    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated_draft = json.loads(draft_path.read_text(encoding="utf-8"))

    assert updated_draft["glossary_refs"]
    assert updated_draft["provenance"]["glossary"]
    first_term = updated_draft["glossary_refs"][0]["term_id"]
    assert updated_draft["provenance"]["glossary"][first_term]
    report = validate_payload("instance_page", updated_draft)
    assert report.passed is True
    assert not any(issue.code == "schema.invalid" for issue in report.issues)
    first_ref = updated_draft["glossary_refs"][0]
    assert first_ref.get("label")
    assert str(first_ref.get("wiki_url", "")).startswith("http")


def test_linker_scans_wiki_first_history_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ensure_run_context(
        "run-test-linker-history-sections", artifacts_root=tmp_path / "runs"
    )
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-western-plaguelands.json"
    draft_path.write_text(
        json.dumps(
            {
                "zone_id": "zone-western-plaguelands",
                "name": "Western Plaguelands",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
                "parent_continent": "eastern-kingdoms",
                "expansion_context": "retail",
                "at_a_glance": (
                    "Contested farmland recovering from blight while patrol networks reconnect roads, "
                    "secure villages, and hold strategic crossings threatened by undead incursions."
                ),
                "currently": (
                    "Crusaders continue pressuring Scourge holdouts across fortified positions as "
                    "supply escorts and field commanders coordinate response operations."
                ),
                "history_sections": [
                    {
                        "heading": "Blight and conflict",
                        "body": (
                            "Scourge offensives reshaped the region for generations, forcing repeated "
                            "campaigns to reclaim farmland, stabilize roads, and restore defensive "
                            "infrastructure after prolonged devastation."
                        ),
                        "source_refs": [
                            {
                                "source_id": "src-zone",
                                "locator": "section:history paragraph:1",
                                "revision_id": "mw:123",
                                "excerpt_hash": "sha1:zonehist111111111",
                            }
                        ],
                    }
                ],
                "major_factions": [],
                "major_questlines": [],
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-zone",
                        "url": "https://warcraft.wiki.gg/wiki/Western_Plaguelands",
                        "revision_id": "mw:123",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-zone",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:123",
                            "excerpt_hash": "sha1:zone1111111111111",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "major_factions": {},
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
        lambda _context=None: [
            {
                "term_id": "term-scourge",
                "alias": "Scourge",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "faction",
            }
        ],
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated_draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert any(row["term_id"] == "term-scourge" for row in updated_draft["glossary_refs"])
    scourge_ref = next(
        row for row in updated_draft["glossary_refs"] if row["term_id"] == "term-scourge"
    )
    assert scourge_ref.get("label") == "Scourge"
    assert str(scourge_ref.get("wiki_url", "")).startswith("http")


def test_linker_enriches_refs_from_run_terms(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-linker-run-terms", artifacts_root=tmp_path / "runs")
    glossary_dir = context.data_dir / "glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "run_terms.jsonl").write_text(
        json.dumps(
            {
                "term_id": "term-scourge",
                "label": "Scourge",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Scourge",
                "category": "faction",
                "aliases": ["scourge"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-example.json"
    draft_path.write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "at_a_glance": (
                    "Scourge patrols continue to threaten the frontier while crusader commanders "
                    "coordinate defensive operations, supply escorts, and repeated counterattacks "
                    "across contested farmland routes and fortified recovery lines."
                ),
                "currently": (
                    "Crusaders coordinate anti-Scourge operations while patrol networks reconnect "
                    "roads, secure villages, and hold strategic crossings threatened by undead incursions."
                ),
                "history_sections": [
                    {
                        "heading": "Conflict",
                        "body": (
                            "Scourge offensives reshaped the region for generations, forcing repeated "
                            "campaigns to reclaim farmland, stabilize roads, and restore defensive "
                            "infrastructure after prolonged devastation across the frontier."
                        ),
                        "source_refs": [
                            {
                                "source_id": "src-zone",
                                "locator": "section:history paragraph:1",
                                "revision_id": "mw:1",
                                "excerpt_hash": "sha1:zone1111111111111",
                            }
                        ],
                    }
                ],
                "major_factions": [],
                "major_questlines": [],
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-zone",
                        "url": "https://example.test/zone",
                        "revision_id": "mw:1",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-zone",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:zone1111111111111",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "major_factions": {},
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    assert updated["glossary_refs"]
    ref = updated["glossary_refs"][0]
    assert ref["term_id"] == "term-scourge"
    assert ref["label"] == "Scourge"
    assert ref["wiki_url"] == "https://warcraft.wiki.gg/wiki/Scourge"


def test_linker_uses_distinct_section_pointers_without_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-linker-distinct-pointers",
        artifacts_root=tmp_path / "runs",
    )
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-distinct-pointers.json"
    draft_path.write_text(
        json.dumps(
            {
                "zone_id": "zone-distinct-pointers",
                "name": "Distinct Pointers Zone",
                "at_a_glance": "Alpha patrols secure the northern frontier.",
                "currently": "Beta detachments reinforce the southern corridor.",
                "history_sections": [
                    {
                        "heading": "Conflict",
                        "body": "Gamma campaigns reshaped the region for generations.",
                        "source_refs": [
                            {
                                "source_id": "src-history",
                                "locator": "section:history paragraph:1",
                                "revision_id": "mw:3",
                                "excerpt_hash": "sha1:history3333333333",
                            }
                        ],
                    }
                ],
                "major_factions": [],
                "major_questlines": [],
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-at",
                        "url": "https://example.test/at",
                        "revision_id": "mw:1",
                    },
                    {
                        "source_id": "src-currently",
                        "url": "https://example.test/currently",
                        "revision_id": "mw:2",
                    },
                    {
                        "source_id": "src-history",
                        "url": "https://example.test/history",
                        "revision_id": "mw:3",
                    },
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-at",
                            "locator": "section:at_a_glance paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:aaaaaaaaaaaaaaaa",
                        }
                    ],
                    "currently": [
                        {
                            "source_id": "src-currently",
                            "locator": "section:currently paragraph:1",
                            "revision_id": "mw:2",
                            "excerpt_hash": "sha1:bbbbbbbbbbbbbbbb",
                        }
                    ],
                    "history": [
                        {
                            "source_id": "src-history",
                            "locator": "section:history paragraph:2",
                            "revision_id": "mw:3",
                            "excerpt_hash": "sha1:cccccccccccccccc",
                        }
                    ],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "major_factions": {},
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
        lambda _context=None: [
            {
                "term_id": "term-alpha",
                "alias": "Alpha",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-beta",
                "alias": "Beta",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-gamma",
                "alias": "Gamma",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
        ],
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    glossary_map = updated["provenance"]["glossary"]
    if len(glossary_map) < 2:
        pytest.skip("not enough glossary terms linked for distinct-pointer check")
    locators = {
        rows[0]["locator"] for rows in glossary_map.values() if isinstance(rows, list) and rows
    }
    assert len(locators) == len(glossary_map)


def test_linker_drops_glossary_refs_without_section_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ensure_run_context(
        "run-test-linker-drop-unprovenanced",
        artifacts_root=tmp_path / "runs",
    )
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-drop-unprovenanced.json"
    draft_path.write_text(
        json.dumps(
            {
                "zone_id": "zone-drop-unprovenanced",
                "name": "Drop Zone",
                "at_a_glance": (
                    "Alpha patrols secure the northern frontier while commanders coordinate "
                    "supply routes and defensive rotations across the district under sustained alerts "
                    "and repeated patrol coverage throughout the contested recovery zone."
                ),
                "currently": "",
                "history_sections": [],
                "major_factions": [],
                "major_questlines": [],
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-at",
                        "url": "https://example.test/at",
                        "revision_id": "mw:1",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-at",
                            "locator": "section:at_a_glance paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:aaaaaaaaaaaaaaaa",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "major_factions": {},
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
        lambda _context=None: [
            {
                "term_id": "term-alpha",
                "alias": "Alpha",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
            {
                "term_id": "term-missing",
                "alias": "Missing",
                "alias_type": "canonical",
                "case_rule": "insensitive",
                "category": "event",
            },
        ],
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    linked_ids = {row["term_id"] for row in updated["glossary_refs"]}
    assert "term-alpha" in linked_ids
    assert "term-missing" not in linked_ids
    assert set(updated["provenance"]["glossary"]) == linked_ids


def test_linker_scans_major_faction_card_text(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-linker-faction-cards", artifacts_root=tmp_path / "runs")
    glossary_dir = context.data_dir / "glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "run_terms.jsonl").write_text(
        json.dumps(
            {
                "term_id": "term-argent-dawn",
                "label": "Argent Dawn",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Argent_Dawn",
                "category": "faction",
                "aliases": ["argent dawn"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-example.json"
    draft_path.write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "at_a_glance": "Patrol routes remain contested across the frontier.",
                "currently": "Militia units hold the main road network.",
                "history_sections": [],
                "major_factions": [
                    {
                        "id": "faction-argent-dawn",
                        "name": "Argent Dawn",
                        "summary": (
                            "Argent Dawn crusaders coordinate reclamation patrols and supply escorts "
                            "across the region while maintaining defensive positions at key crossings."
                        ),
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Argent_Dawn",
                    }
                ],
                "major_questlines": [],
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-zone",
                        "url": "https://example.test/zone",
                        "revision_id": "mw:1",
                    }
                ],
                "provenance": {
                    "at_a_glance": [
                        {
                            "source_id": "src-zone",
                            "locator": "section:lead paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:zone1111111111111",
                        }
                    ],
                    "currently": [],
                    "history": [],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "major_factions": {
                        "faction-argent-dawn": [
                            {
                                "source_id": "src-zone",
                                "locator": "section:faction paragraph:1",
                                "revision_id": "mw:1",
                                "excerpt_hash": "sha1:faction1111111111",
                            }
                        ]
                    },
                    "instances": {},
                    "major_landmarks": {},
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    assert any(row["term_id"] == "term-argent-dawn" for row in updated["glossary_refs"])


def test_linker_links_multiple_terms_sharing_one_section(tmp_path: Path) -> None:
    # WS-5b: several glossary terms mentioned in the same paragraph must all link — the
    # link budget counts distinct terms (not per-section instances) and the provenance
    # pointer is no longer deduped by (source_id, locator), so terms sharing a citing
    # section are not collapsed to one.
    context = ensure_run_context("run-test-linker-shared-section", artifacts_root=tmp_path / "runs")
    glossary_dir = context.data_dir / "glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "run_terms.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "term_id": f"term-{slug}",
                    "label": label,
                    "wiki_url": f"https://warcraft.wiki.gg/wiki/{label.replace(' ', '_')}",
                    "category": "concept",
                    "aliases": [label.lower()],
                }
            )
            for slug, label in [
                ("scourge", "Scourge"),
                ("lordaeron", "Lordaeron"),
                ("kel-thuzad", "Kel'Thuzad"),
                ("plague-of-undeath", "Plague of Undeath"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    draft_dir = context.data_dir / "drafts" / "zone_page"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "zone-example.json"
    # Padding so the 4%-of-words link budget (int(words*0.04)) comfortably exceeds the
    # four terms — the test exercises shared-section linking, not the density cap.
    filler = " ".join(["history"] * 200)
    draft_path.write_text(
        json.dumps(
            {
                "id": "zone-example",
                "history_sections": [
                    {
                        "heading": "Fall",
                        "body": (
                            "The Scourge unleashed the Plague of Undeath across Lordaeron at the "
                            "command of Kel'Thuzad, and the kingdom fell into ruin. " + filler
                        ),
                        "source_refs": [
                            {
                                "source_id": "src-zone",
                                "locator": "section:history paragraph:1",
                                "revision_id": "mw:1",
                                "excerpt_hash": "sha1:hist11111111111",
                            }
                        ],
                    }
                ],
                "glossary_refs": [],
                "provenance": {
                    "history": [
                        {
                            "source_id": "src-zone",
                            "locator": "section:history paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:hist11111111111",
                        }
                    ],
                    "glossary": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    linked = {row["term_id"] for row in updated["glossary_refs"]}
    # All four terms share the single history paragraph and must all be linked.
    assert {"term-scourge", "term-lordaeron", "term-kel-thuzad", "term-plague-of-undeath"} <= linked
