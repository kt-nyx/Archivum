#!/usr/bin/env python3
"""Semantic acceptance checks for a pipeline run (zone-agnostic)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.discovery.entity_typing import is_valid_quest_graph_link
from pipeline.discovery.storyline_html import parse_storyline_html


def _fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_zone_target(run_root: Path, zone_id: str | None) -> tuple[Path, str, str]:
    draft_dir = run_root / "data" / "drafts" / "zone_page"
    if not draft_dir.exists():
        _fail(f"missing zone draft directory at {draft_dir}")

    if zone_id:
        draft_path = draft_dir / f"{zone_id}.json"
        if not draft_path.exists():
            _fail(f"missing zone draft at {draft_path}")
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"zone draft is not a JSON object: {draft_path}")
        zone_name = str(draft.get("name", "")).strip() or zone_id
        return draft_path, zone_id, zone_name

    draft_paths = sorted(draft_dir.glob("zone-*.json"))
    if len(draft_paths) == 1:
        draft_path = draft_paths[0]
        resolved_id = draft_path.stem
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"zone draft is not a JSON object: {draft_path}")
        zone_name = str(draft.get("name", "")).strip() or resolved_id
        return draft_path, resolved_id, zone_name

    manifest_path = run_root / "source_manifest.json"
    manifest = _load_json(manifest_path)
    zone_ids: list[str] = []
    if isinstance(manifest, list):
        for row in manifest:
            if not isinstance(row, dict):
                continue
            if str(row.get("entity_type", "")).strip() != "zone":
                continue
            entity_id = str(row.get("entity_id", "")).strip()
            if entity_id and entity_id not in zone_ids:
                zone_ids.append(entity_id)
    if len(zone_ids) == 1:
        resolved_id = zone_ids[0]
        draft_path = draft_dir / f"{resolved_id}.json"
        if not draft_path.exists():
            _fail(f"manifest zone {resolved_id!r} has no draft at {draft_path}")
        draft = _load_json(draft_path)
        if not isinstance(draft, dict):
            _fail(f"zone draft is not a JSON object: {draft_path}")
        zone_name = str(draft.get("name", "")).strip() or resolved_id
        return draft_path, resolved_id, zone_name

    _fail(
        "could not resolve zone target: pass --zone-id or ensure the run has exactly one zone draft "
        f"(found {len(draft_paths)} drafts, {len(zone_ids)} zone manifest rows)"
    )


def check_run(run_root: Path, *, zone_id: str | None = None) -> None:
    draft_path, resolved_zone_id, zone_name = _resolve_zone_target(run_root, zone_id)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if not draft.get("major_questlines"):
        _fail("major_questlines is empty")
    for row in draft.get("major_questlines", []):
        title = str(row.get("title", "")).strip()
        if not title:
            _fail("major_questlines contains empty title")
        valid, reasons = is_valid_quest_graph_link(
            f"/wiki/{title.replace(' ', '_')}",
            zone_name=zone_name,
        )
        if not valid:
            _fail(f"major_questlines title denied by quest graph classifier: {title!r} ({reasons})")
    if not draft.get("location_cards"):
        _fail("location_cards is empty")
    if len(draft.get("sources", [])) < 2:
        _fail("expected multiple sources on zone draft")
    history = draft.get("history_sections") or []
    if not history:
        _fail("history_sections is empty")
    blob = json.dumps(history)
    if "&#91;" in blob or "History 1" in blob:
        _fail("history_sections contain raw passthrough markers")

    v3_path = run_root / "data" / "discovery" / "zone_quest_graph_v3.json"
    snapshots_path = run_root / "data" / "ingest" / "source_snapshots.json"
    if v3_path.exists() and snapshots_path.exists():
        v3_rows = json.loads(v3_path.read_text(encoding="utf-8"))
        v3_titles = {
            str(row.get("title", "")).lower()
            for row in v3_rows
            if row.get("node_type") == "quest" and str(row.get("zone_id", "")) == resolved_zone_id
        }
        snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
        storyline = next(
            (
                row
                for row in snapshots
                if isinstance(row, dict)
                and str(row.get("entity_id", "")) == resolved_zone_id
                and str(row.get("auxiliary_role", "")) == "storyline"
            ),
            None,
        )
        if storyline is not None:
            parse_html = str(storyline.get("parse_html", "")).strip()
            if parse_html:
                expected_titles = {
                    str(row.get("title", "")).lower()
                    for row in parse_storyline_html(
                        parse_html,
                        zone_id=resolved_zone_id,
                        zone_name=zone_name,
                    )
                }
                extra = v3_titles - expected_titles
                if extra:
                    _fail(
                        "v3 quest graph includes quests not parsed from storyline list items: "
                        f"{sorted(extra)}"
                    )

    evidence_path = run_root / "data" / "evidence" / "evidence_packs.jsonl"
    if evidence_path.exists():
        glance_items = 0
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("field_name") != "at_a_glance_input":
                continue
            build_meta = row.get("build_meta") or {}
            if str(build_meta.get("subject_zone_id", "")) not in {"", resolved_zone_id}:
                continue
            glance_items += len(row.get("evidence_items", []))
        if glance_items > 50:
            _fail(f"at_a_glance_input pool exceeds cap: {glance_items}")

    print(f"PASS: semantic checks ok for {run_root.name} ({resolved_zone_id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic acceptance checks for a pipeline run.")
    parser.add_argument("run_root", type=Path, help="Path to artifacts/runs/<run-id>")
    parser.add_argument(
        "--zone-id",
        default=None,
        help="Zone entity id (e.g. zone-western-plaguelands). Auto-detected when omitted.",
    )
    args = parser.parse_args()
    check_run(args.run_root, zone_id=args.zone_id)


if __name__ == "__main__":
    main()
