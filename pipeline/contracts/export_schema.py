"""Export versioned JSON schemas for canonical contracts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from pipeline.contracts.models import (
    ENTITY_MODEL_MAP,
    WIKI_FIRST_ENTITY_MODEL_MAP,
    InclusionDecision,
    SourcePointer,
)

SCHEMA_VERSION = "v1"


def _deterministic_json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def export_all_schemas(output_dir: Path) -> list[Path]:
    """Write all entity schemas to disk in deterministic order."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[Path] = []

    schema_model_map: dict[str, type[BaseModel]] = {
        **ENTITY_MODEL_MAP,
        **WIKI_FIRST_ENTITY_MODEL_MAP,
        "inclusion_decision": InclusionDecision,
        "source_pointer": SourcePointer,
    }

    for entity_name in sorted(schema_model_map):
        model = schema_model_map[entity_name]
        schema = model.model_json_schema()
        destination = output_dir / f"{entity_name}.schema.json"
        destination.write_text(_deterministic_json(schema), encoding="utf-8")
        written_files.append(destination)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "entities": sorted({*ENTITY_MODEL_MAP, *WIKI_FIRST_ENTITY_MODEL_MAP}),
        "contracts": sorted(["inclusion_decision", "source_pointer"]),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(_deterministic_json(manifest), encoding="utf-8")
    written_files.append(manifest_path)
    return written_files


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    export_all_schemas(project_root / "schemas" / SCHEMA_VERSION)


if __name__ == "__main__":
    main()
