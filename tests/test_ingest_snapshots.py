"""Tests for the Slice 12 snapshot loading home (schema guard + re-crawl error)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.ingest.snapshots import (
    SnapshotSchemaError,
    load_source_snapshots,
    validate_snapshot_schema,
)


def _new_shape_snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "source_id": "zone-wpl",
        "entity_id": "zone-western-plaguelands",
        "infobox": {"_title": "Western Plaguelands", "PvP status": "Contested territory"},
        "section_blocks": [
            {
                "section_role": "lead",
                "text": "The Argent Crusade heals the land.",
                "links": [{"anchor_text": "Argent Crusade", "href": "/wiki/Argent_Crusade"}],
            },
            {"section_role": "history", "text": "No links in this paragraph.", "links": []},
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _write(tmp_path: Path, payload: Any) -> Path:
    path = tmp_path / "source_snapshots.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_source_snapshots_accepts_new_shape(tmp_path: Path) -> None:
    path = _write(tmp_path, [_new_shape_snapshot(), "not-a-dict"])
    snapshots = load_source_snapshots(path)
    assert len(snapshots) == 1  # non-dict rows dropped, matching historical loaders
    assert snapshots[0]["source_id"] == "zone-wpl"


def test_load_rejects_snapshot_missing_infobox(tmp_path: Path) -> None:
    old_shape = _new_shape_snapshot()
    del old_shape["infobox"]
    path = _write(tmp_path, [old_shape])
    with pytest.raises(SnapshotSchemaError, match="re-crawl required"):
        load_source_snapshots(path)


def test_load_rejects_block_missing_links(tmp_path: Path) -> None:
    old_shape = _new_shape_snapshot()
    del old_shape["section_blocks"][0]["links"]
    path = _write(tmp_path, [old_shape])
    with pytest.raises(SnapshotSchemaError, match=r"section_blocks\[\]\.links"):
        load_source_snapshots(path)


def test_schema_error_names_the_offending_snapshot(tmp_path: Path) -> None:
    old_shape = _new_shape_snapshot(source_id="aux-faction-argent-crusade", infobox=None)
    path = _write(tmp_path, [old_shape])
    with pytest.raises(SnapshotSchemaError, match="aux-faction-argent-crusade"):
        load_source_snapshots(path)


def test_empty_infobox_and_empty_links_are_valid_data_conditions() -> None:
    # A page with no infobox / a paragraph with no links is data, not schema drift.
    snapshot = _new_shape_snapshot(infobox={})
    validate_snapshot_schema(snapshot, path=Path("source_snapshots.json"))


def test_missing_ok_returns_empty_for_absent_file(tmp_path: Path) -> None:
    path = tmp_path / "source_snapshots.json"
    assert load_source_snapshots(path, missing_ok=True) == []
    with pytest.raises(FileNotFoundError):
        load_source_snapshots(path)


def test_non_array_payload_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, {"not": "a list"})
    with pytest.raises(RuntimeError, match="JSON array"):
        load_source_snapshots(path)
