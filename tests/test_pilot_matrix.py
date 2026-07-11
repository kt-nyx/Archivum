"""Slice 9, item 3: the pilot matrix definition and its run-config manifests are well-formed.

These are evaluation run configurations (pilot names permitted here). The test proves the matrix is
machine-consumable and every referenced manifest validates against the ingest source-manifest schema
with an internally consistent zone/linked-instance pair — so the strict acceptance runs (item 4) can
iterate it without a hand-authored output fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO_ROOT / "evaluation" / "pilot_matrix.json"
MANIFEST_SCHEMA_PATH = REPO_ROOT / "pipeline" / "ingest" / "source_manifest.schema.json"


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pilot_matrix_declares_three_pairs_with_one_hold_out() -> None:
    matrix = _load(MATRIX_PATH)
    assert isinstance(matrix, dict)
    assert matrix["schema_version"] == "pilot_matrix.v1"
    assert matrix["strict_settings"]["fact_check_profile"] == "strict"
    assert matrix["strict_settings"]["release_gate"] is True

    subjects = matrix["subjects"]
    assert isinstance(subjects, list) and len(subjects) == 3
    pair_ids = {subject["pair_id"] for subject in subjects}
    assert pair_ids == {"wpl-scholomance", "desolace-maraudon", "westfall-deadmines"}

    hold_outs = {subject["pair_id"] for subject in subjects if subject["hold_out"]}
    assert hold_outs == {"westfall-deadmines"}


def test_pilot_matrix_manifests_are_schema_valid_and_consistent() -> None:
    matrix = _load(MATRIX_PATH)
    schema = _load(MANIFEST_SCHEMA_PATH)
    validator = Draft202012Validator(schema)

    for subject in matrix["subjects"]:  # type: ignore[index]
        manifest_path = REPO_ROOT / subject["manifest"]
        assert manifest_path.exists(), f"missing manifest for {subject['pair_id']}: {manifest_path}"
        rows = _load(manifest_path)
        errors = sorted(validator.iter_errors(rows), key=lambda err: list(err.path))
        assert not errors, f"{subject['pair_id']} manifest schema errors: {[e.message for e in errors]}"

        assert isinstance(rows, list)
        zone_ids = {
            row["entity_id"] for row in rows if row.get("entity_type") == "zone"
        }
        instance_rows = [row for row in rows if row.get("entity_type") == "instance"]
        # The manifest realises the declared zone + linked instance pair.
        assert subject["zone"]["entity_id"] in zone_ids
        assert any(
            row["entity_id"] == subject["linked_instance"]["entity_id"]
            and row.get("parent_zone_id") == subject["zone"]["entity_id"]
            for row in instance_rows
        )
