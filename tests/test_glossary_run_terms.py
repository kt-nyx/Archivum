from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.common.run_context import ensure_run_context
from pipeline.glossary.run_terms import (
    build_run_terms,
    run_terms_metadata_map,
    run_terms_to_alias_dictionary,
)


def test_build_run_terms_from_zone_and_instance_drafts(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-glossary-terms", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts"
    (drafts_dir / "zone_page").mkdir(parents=True)
    (drafts_dir / "instance_page").mkdir(parents=True)
    (drafts_dir / "zone_page" / "zone-example.json").write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Example_Zone",
                "major_factions": [{"id": "faction-scourge", "name": "Scourge", "summary": "Undead host."}],
                "location_cards": [{"id": "location-outpost", "name": "Frontier Outpost", "summary": "A base."}],
                "instance_links": [{"id": "instance-vault", "name": "Archive Vault", "summary": "A dungeon."}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (drafts_dir / "instance_page" / "instance-vault.json").write_text(
        json.dumps(
            {
                "instance_id": "instance-vault",
                "name": "Archive Vault",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Archive_Vault",
                "key_characters": [{"id": "character-boss", "name": "Archivist Maelor", "summary": "A boss."}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    output_path = build_run_terms(context)
    assert output_path.exists()
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    term_ids = {row["term_id"] for row in rows}
    assert "term-example-zone" in term_ids
    assert "term-scourge" in term_ids
    assert "term-frontier-outpost" in term_ids
    assert "term-archive-vault" in term_ids
    assert "term-archivist-maelor" in term_ids

    scourge = next(row for row in rows if row["term_id"] == "term-scourge")
    assert scourge["category"] == "faction"
    assert scourge["wiki_url"].startswith("https://")

    alias_rows = run_terms_to_alias_dictionary(rows)
    assert any(row["alias"] == "Scourge" and row["alias_type"] == "canonical" for row in alias_rows)
    metadata = run_terms_metadata_map(rows)
    assert metadata["term-scourge"]["label"] == "Scourge"


def test_build_run_terms_deduplicates_shared_labels(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-glossary-dedupe", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts"
    (drafts_dir / "zone_page").mkdir(parents=True)
    (drafts_dir / "zone_page" / "zone-example.json").write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "instance_links": [{"id": "instance-vault", "name": "Example Zone", "summary": "Same label."}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = build_run_terms(context)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    example_rows = [row for row in rows if row["label"] == "Example Zone"]
    assert len(example_rows) == 1


def test_build_run_terms_uses_faction_card_wiki_url(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-glossary-faction-url", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts" / "zone_page"
    drafts_dir.mkdir(parents=True)
    (drafts_dir / "zone-example.json").write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "major_factions": [
                    {
                        "id": "faction-scourge",
                        "name": "Scourge",
                        "summary": "Undead host.",
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Scourge",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = build_run_terms(context)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    scourge = next(row for row in rows if row["term_id"] == "term-scourge")
    assert scourge["wiki_url"] == "https://warcraft.wiki.gg/wiki/Scourge"


def _write_snapshots(context, snapshots: list[dict]) -> None:
    ingest_dir = context.data_dir / "ingest"
    ingest_dir.mkdir(parents=True, exist_ok=True)
    (ingest_dir / "source_snapshots.json").write_text(json.dumps(snapshots, indent=2), encoding="utf-8")


def test_build_run_terms_derives_terms_from_ingest_snapshots(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-glossary-snapshots", artifacts_root=tmp_path / "runs")
    _write_snapshots(
        context,
        [
            {
                "entity_id": "character-thel",
                "entity_type": "character",
                "name": "Thelara Dawnsong",
                "url": "https://warcraft.wiki.gg/wiki/Thelara_Dawnsong",
                "categories": ["Western Plaguelands NPCs", "Humans"],
                "infobox": {"Aliases": "The Dawnsinger; Lady Thelara", "Status": "Alive"},
            }
        ],
    )
    output_path = build_run_terms(context)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    thel = next(row for row in rows if row["term_id"] == "term-thelara-dawnsong")
    assert thel["category"] == "person"
    assert thel["wiki_url"] == "https://warcraft.wiki.gg/wiki/Thelara_Dawnsong"
    # Infobox alternate-name fields are harvested as aliases (split on ; , / and newlines).
    assert "the dawnsinger" in thel["aliases"]
    assert "lady thelara" in thel["aliases"]
    # Non-alias infobox fields (e.g. Status) are ignored.
    assert "alive" not in thel["aliases"]


def test_build_run_terms_classifies_unknown_type_from_categories(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-glossary-category-signal", artifacts_root=tmp_path / "runs")
    _write_snapshots(
        context,
        [
            {
                "entity_id": "thing-mystery",
                "entity_type": "",
                "name": "Order of Embers",
                "url": "https://warcraft.wiki.gg/wiki/Order_of_Embers",
                "categories": ["Organizations", "Drustvar"],
                "infobox": {},
            }
        ],
    )
    output_path = build_run_terms(context)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    order = next(row for row in rows if row["term_id"] == "term-order-of-embers")
    # No discovered entity_type -> the structural MediaWiki category refines it.
    assert order["category"] == "faction"


def test_build_run_terms_upgrades_generic_category_from_snapshot(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-glossary-upgrade", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts" / "zone_page"
    drafts_dir.mkdir(parents=True)
    # The canonical map types this entity as the generic "concept"...
    canonical_dir = context.data_dir / "discovery"
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "canonical_entity_map.jsonl").write_text(
        json.dumps(
            {
                "entity_id": "x-blightcaller",
                "entity_type": "concept",
                "wiki_title": "Nathanos Blightcaller",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Nathanos_Blightcaller",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # ...while the ingest snapshot carries the specific category signal.
    _write_snapshots(
        context,
        [
            {
                "entity_id": "x-blightcaller",
                "entity_type": "",
                "name": "Nathanos Blightcaller",
                "url": "https://warcraft.wiki.gg/wiki/Nathanos_Blightcaller",
                "categories": ["Forsaken NPCs"],
                "infobox": {},
            }
        ],
    )
    output_path = build_run_terms(context)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    nathanos = next(row for row in rows if row["term_id"] == "term-nathanos-blightcaller")
    assert nathanos["category"] == "person"


def test_glossary_pipeline_terms_link_validate_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.addon.build_bundle import build_addon_bundle
    from pipeline.linker.linker import run_glossary_linker
    from pipeline.validate.engine import validate_payload

    monkeypatch.setenv("LORE_GLOSSARY_MIN_TERMS", "2")
    context = ensure_run_context("run-test-glossary-e2e", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts" / "zone_page"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / "zone-example.json"
    draft_path.write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "wiki_url": "https://warcraft.wiki.gg/wiki/Example_Zone",
                "parent_continent": "eastern-kingdoms",
                "expansion_context": "retail",
                "at_a_glance": (
                    "Scourge patrols continue to threaten Example Zone while crusader commanders "
                    "coordinate defensive operations, supply escorts, and repeated counterattacks."
                ),
                "currently": (
                    "Crusaders coordinate anti-Scourge operations while patrol networks reconnect "
                    "roads, secure villages, and hold strategic crossings threatened by undead incursions."
                ),
                "history_sections": [
                    {
                        "heading": "Conflict",
                        "body": (
                            "Scourge offensives reshaped Example Zone for generations, forcing repeated "
                            "campaigns to reclaim farmland, restore defensive infrastructure, and hold "
                            "strategic crossings against renewed undead incursions across the frontier."
                        ),
                    }
                ],
                "major_factions": [
                    {
                        "id": "faction-scourge",
                        "name": "Scourge",
                        "summary": (
                            "Scourge forces maintain pressure across Example Zone through patrol networks "
                            "and fortified positions that threaten nearby settlements."
                        ),
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Scourge",
                    }
                ],
                "major_questlines": [],
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [],
                "sources": [
                    {
                        "source_id": "src-zone",
                        "url": "https://warcraft.wiki.gg/wiki/Example_Zone",
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
                    "currently": [
                        {
                            "source_id": "src-zone",
                            "locator": "section:currently paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:zone2222222222222",
                        }
                    ],
                    "history": [
                        {
                            "source_id": "src-zone",
                            "locator": "section:history paragraph:1",
                            "revision_id": "mw:1",
                            "excerpt_hash": "sha1:zone3333333333333",
                        }
                    ],
                    "major_questlines_alliance": {},
                    "major_questlines_horde": {},
                    "major_questlines_shared": {},
                    "major_characters": {},
                    "major_factions": {
                        "faction-scourge": [
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
    build_run_terms(context)
    run_glossary_linker(context, [draft_path], max_entity_concurrency=1)
    updated = json.loads(draft_path.read_text(encoding="utf-8"))
    report = validate_payload("zone_page", updated)
    assert updated["glossary_refs"]
    assert updated["provenance"]["glossary"]
    for term_id in {ref["term_id"] for ref in updated["glossary_refs"]}:
        assert term_id in updated["provenance"]["glossary"]
    glossary_issues = [
        issue
        for issue in report.issues
        if issue.path.startswith("$.glossary_refs") or issue.code.startswith("structure.glossary_ref")
    ]
    assert not glossary_issues
    for ref in updated["glossary_refs"]:
        assert ref.get("label")
        assert str(ref.get("wiki_url", "")).startswith("http")
    bundle_root = build_addon_bundle(context)
    glossary_lookup = json.loads((bundle_root / "lookup" / "glossary_refs.json").read_text(encoding="utf-8"))
    for ref in updated["glossary_refs"]:
        term_id = ref["term_id"]
        assert term_id in glossary_lookup
        assert str(glossary_lookup[term_id].get("wiki_url", "")).startswith("http")


def test_build_bundle_logs_static_dictionary_fallback_when_no_run_terms(tmp_path: Path) -> None:
    from pipeline.addon.build_bundle import build_addon_bundle

    context = ensure_run_context("run-test-glossary-static-log", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts" / "zone_page"
    drafts_dir.mkdir(parents=True)
    (drafts_dir / "zone-example.json").write_text(
        json.dumps(
            {
                "zone_id": "zone-example",
                "name": "Example Zone",
                "location_cards": [],
                "instance_links": [],
                "glossary_refs": [{"term_id": "term-scourge"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # No run_terms.jsonl is written, so metadata must fall back to the static dict.
    build_addon_bundle(context)
    trace_path = context.trace_log_path()
    assert trace_path.exists()
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in trace_lines if line.strip()]
    fallback_events = [
        event
        for event in events
        if event.get("details", {}).get("glossary") == "static_dictionary_fallback"
    ]
    assert fallback_events, "expected a degraded trace event for the static-dictionary fallback"
    assert fallback_events[0]["status"] == "degraded"
