import json
from pathlib import Path
from typing import Any, cast

from pipeline.contracts.export_schema import export_all_schemas


def test_schema_export_is_deterministic(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    export_all_schemas(first_dir)
    export_all_schemas(second_dir)

    first_files = sorted(path.name for path in first_dir.glob("*.json"))
    second_files = sorted(path.name for path in second_dir.glob("*.json"))
    assert first_files == second_files

    for filename in first_files:
        assert (first_dir / filename).read_text(encoding="utf-8") == (
            second_dir / filename
        ).read_text(encoding="utf-8")

    manifest = cast(
        dict[str, Any], json.loads((first_dir / "manifest.json").read_text(encoding="utf-8"))
    )
    assert manifest["contracts"] == ["inclusion_decision", "source_pointer"]
    assert "sub_zone" in manifest["entities"]
    assert (first_dir / "inclusion_decision.schema.json").exists()
    assert (first_dir / "source_pointer.schema.json").exists()

    asset_schema = cast(
        dict[str, Any], json.loads((first_dir / "asset.schema.json").read_text(encoding="utf-8"))
    )
    required = set(cast(list[str], asset_schema["required"]))
    assert "allowed_use_reason" in required
    assert "sources" in required

    zone_schema = cast(
        dict[str, Any], json.loads((first_dir / "zone.schema.json").read_text(encoding="utf-8"))
    )
    defs = cast(dict[str, Any], zone_schema["$defs"])
    questline_card_schema = cast(dict[str, Any], defs["QuestlineCard"])
    questline_required = set(cast(list[str], questline_card_schema["required"]))
    questline_properties = cast(dict[str, Any], questline_card_schema["properties"])
    assert "inclusion_decision" in questline_required
    assert "depends_on_parent_context" in questline_properties
    assert "dependency_note" in questline_properties
