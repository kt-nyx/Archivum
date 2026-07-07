"""Single home for loading ingest source snapshots (Slice 12 schema guard).

From Slice 12 on, the ingest schema requires every snapshot to carry ``infobox``
(``{}`` when the page genuinely has none) and every section block to carry
``links`` (``[]`` when the paragraph has none). There are no dual-shape loaders:
a snapshot missing the new keys predates the schema and its whole run is stale —
the fix is a fresh crawl, never a special case. Every pipeline consumer of
``source_snapshots.json`` must load it through :func:`load_source_snapshots`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SnapshotSchemaError(RuntimeError):
    """A source snapshot predates the required ingest schema (re-crawl required)."""


def _schema_error(path: Path, snapshot: dict[str, Any], missing: str) -> SnapshotSchemaError:
    source_id = str(snapshot.get("source_id", "")).strip() or "<unknown source_id>"
    return SnapshotSchemaError(
        f"snapshot '{source_id}' in '{path}' is missing required key {missing}: "
        "it predates the Slice 12 ingest schema (per-block inline links + infobox) — "
        "re-crawl required: regenerate this run with a fresh crawl instead of reusing "
        "pre-Slice-12 ingest artifacts"
    )


def validate_snapshot_schema(snapshot: dict[str, Any], *, path: Path) -> None:
    """Reject a snapshot that predates the required ingest schema.

    Required from Slice 12 on: ``infobox`` is a dict (empty when the page has no
    infobox — a data condition, not a schema hole) and every ``section_blocks``
    entry carries a ``links`` list (empty when the paragraph has none).
    """
    if not isinstance(snapshot.get("infobox"), dict):
        raise _schema_error(path, snapshot, "'infobox'")
    section_blocks = snapshot.get("section_blocks")
    if not isinstance(section_blocks, list):
        raise _schema_error(path, snapshot, "'section_blocks'")
    for block in section_blocks:
        if isinstance(block, dict) and not isinstance(block.get("links"), list):
            raise _schema_error(path, snapshot, "'section_blocks[].links'")


def load_source_snapshots(path: Path, *, missing_ok: bool = False) -> list[dict[str, Any]]:
    """Load and schema-check ``source_snapshots.json`` (the one loading home).

    Returns the snapshot dicts (non-dict rows are dropped, matching the historical
    loaders). With ``missing_ok`` a missing file yields ``[]`` for consumers that
    treat snapshots as optional context. A malformed payload or an old-shape
    snapshot raises: :class:`SnapshotSchemaError` carries the "re-crawl required"
    remedy.
    """
    if missing_ok and not path.exists():
        return []
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, list):
        raise RuntimeError(f"'{path}' must be a JSON array of source snapshots")
    snapshots = [row for row in blob if isinstance(row, dict)]
    for snapshot in snapshots:
        validate_snapshot_schema(snapshot, path=path)
    return snapshots
