"""Slice 12 snapshot-shape helper for tests that hand-build source snapshots."""

from __future__ import annotations

from typing import Any


def with_required_snapshot_schema(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upgrade hand-built snapshot dicts to the Slice 12 required ingest shape.

    The snapshot load guard (``pipeline.ingest.snapshots``) rejects snapshots
    without ``infobox`` and per-block ``links``; tests that write minimal
    ``source_snapshots.json`` fixtures represent post-Slice-12 crawls, so the
    required keys are filled with their "none present" values (``{}`` / ``[]``)
    unless the test set them explicitly. Mutates and returns ``snapshots``.
    """
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        snapshot.setdefault("infobox", {})
        blocks = snapshot.setdefault("section_blocks", [])
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict):
                    block.setdefault("links", [])
    return snapshots
