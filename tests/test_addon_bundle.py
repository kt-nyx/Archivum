from __future__ import annotations

import json
from pathlib import Path

from pipeline.addon.build_bundle import build_addon_bundle
from pipeline.common.run_context import ensure_run_context


def test_build_addon_bundle_writes_manifest_and_indexes(tmp_path: Path) -> None:
    context = ensure_run_context("run-test-addon-bundle", artifacts_root=tmp_path / "runs")
    drafts_dir = context.data_dir / "drafts"
    (drafts_dir / "zone_page").mkdir(parents=True, exist_ok=True)
    (drafts_dir / "instance_page").mkdir(parents=True, exist_ok=True)

    (drafts_dir / "zone_page" / "zone-western-plaguelands.json").write_text(
        json.dumps(
            {
                "zone_id": "zone-western-plaguelands",
                "location_cards": [{"id": "location-hearthglen", "name": "Hearthglen"}],
                "instance_links": [{"id": "instance-scholomance", "name": "Scholomance"}],
                "glossary_refs": [
                    {
                        "term_id": "term-scourge",
                        "label": "Scourge",
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Scourge",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (drafts_dir / "instance_page" / "instance-scholomance.json").write_text(
        json.dumps(
            {
                "instance_id": "instance-scholomance",
                "glossary_refs": [
                    {
                        "term_id": "term-gandling",
                        "label": "Darkmaster Gandling",
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    glossary_dir = context.data_dir / "glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "run_terms.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "term_id": "term-scourge",
                        "label": "Scourge",
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Scourge",
                        "category": "faction",
                        "aliases": ["scourge"],
                    }
                ),
                json.dumps(
                    {
                        "term_id": "term-gandling",
                        "label": "Darkmaster Gandling",
                        "wiki_url": "https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
                        "category": "person",
                        "aliases": ["darkmaster gandling"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    validate_report_path = context.reports_dir / "validate"
    validate_report_path.mkdir(parents=True, exist_ok=True)
    (validate_report_path / "validation_report.json").write_text(
        json.dumps({"passed": False, "issues": [{"code": "schema.invalid"}]}, indent=2),
        encoding="utf-8",
    )

    output_root = build_addon_bundle(context)
    assert (output_root / "manifest.json").exists()
    assert (output_root / "lookup" / "location_cards.json").exists()
    assert (output_root / "lookup" / "glossary_refs.json").exists()
    assert (output_root / "lookup" / "glossary_terms.json").exists()
    assert (output_root / "nav" / "index.json").exists()
    bundle_validation = json.loads((output_root / "validation_report.json").read_text(encoding="utf-8"))
    assert bundle_validation["passed"] is False
    glossary_refs = json.loads((output_root / "lookup" / "glossary_refs.json").read_text(encoding="utf-8"))
    assert "term-scourge" in glossary_refs
    assert "term-gandling" in glossary_refs
    glossary_terms = json.loads(
        (output_root / "lookup" / "glossary_terms.json").read_text(encoding="utf-8")
    )
    assert glossary_terms["term-scourge"]["wiki_url"].endswith("/Scourge")
    assert glossary_terms["term-gandling"]["wiki_url"].endswith("/Darkmaster_Gandling")
