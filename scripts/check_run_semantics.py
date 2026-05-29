#!/usr/bin/env python3
"""Semantic acceptance checks for a pipeline run (zone-agnostic)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pipeline.discovery.entity_typing import is_valid_quest_graph_link, normalize_title
from pipeline.discovery.storyline_html import parse_storyline_html
from pipeline.discovery.world_registry import entry_kinds

_GEOGRAPHY_KINDS = frozenset({"zone", "continent", "capital", "region", "instance"})
_FILLER_RE = re.compile(r"\blocated in\b|\bis a zone\b|\bis located\b", re.IGNORECASE)
_MAX_CLUSTER_CARDS = 8


class SemanticCheckError(Exception):
    """Raised when a semantic acceptance check fails."""


def _fail(message: str) -> None:
    raise SemanticCheckError(message)


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


def _cluster_ids_from_v3(v3_rows: list[dict[str, Any]], zone_id: str) -> set[str]:
    return {
        str(row.get("cluster_id", "")).strip()
        for row in v3_rows
        if isinstance(row, dict)
        and str(row.get("zone_id", "")) == zone_id
        and str(row.get("node_type", "")) == "quest"
        and str(row.get("cluster_id", "")).strip()
    }


def check_run(run_root: Path, *, zone_id: str | None = None) -> None:
    draft_path, resolved_zone_id, zone_name = _resolve_zone_target(run_root, zone_id)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if not draft.get("major_questlines"):
        _fail("major_questlines is empty")
    zone_lower = normalize_title(zone_name)
    for row in draft.get("major_questlines", []):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        if not title:
            _fail("major_questlines contains empty title")
        title_kinds = entry_kinds(title)
        if title_kinds & _GEOGRAPHY_KINDS:
            _fail(f"major_questlines cluster title is a geography hub: {title!r}")
        if title.lower().endswith(" quests"):
            _fail(f"major_questlines cluster title looks like an achievement hub: {title!r}")
        cta = str(row.get("cta_hook", "")).strip()
        if zone_lower and zone_lower in normalize_title(cta):
            _fail(f"major_questlines cta_hook reads like zone-description filler: {cta!r}")
        if _FILLER_RE.search(cta):
            _fail(f"major_questlines cta_hook reads like zone-description filler: {cta!r}")
        wiki_refs = row.get("wiki_refs", [])
        if not isinstance(wiki_refs, list) or not wiki_refs:
            _fail(f"major_questlines card missing wiki_refs: {title!r}")
        for ref in wiki_refs:
            link = str(ref).strip()
            if not link.startswith("/wiki/"):
                link = f"/wiki/{link.replace(' ', '_')}"
            valid, reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
            if not valid:
                _fail(f"major_questlines wiki_ref denied by quest graph classifier: {link!r} ({reasons})")
    cards = [row for row in draft.get("major_questlines", []) if isinstance(row, dict)]
    if len(cards) > _MAX_CLUSTER_CARDS:
        _fail(f"major_questlines exceeds cluster card cap ({len(cards)} > {_MAX_CLUSTER_CARDS})")

    from pipeline.generate.draft.prose_lint import (
        MAX_HISTORY_SECTIONS,
        MIN_HISTORY_SECTIONS,
        lint_at_a_glance,
        lint_currently,
        lint_history_sections,
    )

    at_a_glance = str(draft.get("at_a_glance", "")).strip()
    if not at_a_glance:
        _fail("at_a_glance is empty")
    for issue in lint_at_a_glance(at_a_glance, zone_name=zone_name):
        _fail(f"at_a_glance quality check failed: {issue}")

    currently = str(draft.get("currently", "")).strip()
    if not currently:
        _fail("currently is empty")
    for issue in lint_currently(currently, zone_name=zone_name):
        _fail(f"currently quality check failed: {issue}")

    history = draft.get("history_sections") or []
    if not history:
        _fail("history_sections is empty")
    history_issues = lint_history_sections(history, max_sections=MAX_HISTORY_SECTIONS)
    for issue in history_issues:
        _fail(f"history_sections quality check failed: {issue}")
    if len(history) > MAX_HISTORY_SECTIONS:
        _fail(f"history_sections exceeds cap ({len(history)} > {MAX_HISTORY_SECTIONS})")

    blob = json.dumps(history)
    if "&#91;" in blob or "History 1" in blob:
        _fail("history_sections contain raw passthrough markers")

    from pipeline.generate.draft.faction_lint import lint_faction_summary
    from pipeline.generate.draft.faction_scoring import (
        MAX_FACTION_CARDS,
        MIN_FACTION_CARDS,
        alliance_horde_conflict_met,
    )

    major_factions = draft.get("major_factions") or []
    faction_cards = [row for row in major_factions if isinstance(row, dict)]
    for card in faction_cards:
        card_id = str(card.get("id", "")).strip()
        if not card_id.startswith("faction-"):
            _fail(f"major_factions card id is not faction-scoped: {card_id!r}")
        summary = str(card.get("summary", "")).strip()
        if not summary:
            _fail(f"major_factions card missing summary: {card_id!r}")
        for issue in lint_faction_summary(summary, zone_name=zone_name):
            _fail(f"major_factions quality check failed for {card_id!r}: {issue}")
    if len(faction_cards) > MAX_FACTION_CARDS:
        _fail(f"major_factions exceeds cap ({len(faction_cards)} > {MAX_FACTION_CARDS})")

    if not draft.get("location_cards"):
        _fail("location_cards is empty")
    if len(draft.get("sources", [])) < 2:
        _fail("expected multiple sources on zone draft")

    v3_path = run_root / "data" / "discovery" / "zone_quest_graph_v3.json"
    snapshots_path = run_root / "data" / "ingest" / "source_snapshots.json"
    v3_rows: list[dict[str, Any]] = []
    if v3_path.exists():
        blob = _load_json(v3_path)
        if isinstance(blob, list):
            v3_rows = [row for row in blob if isinstance(row, dict)]

    if v3_rows and snapshots_path.exists():
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

    if v3_rows:
        expected_clusters = _cluster_ids_from_v3(v3_rows, resolved_zone_id)
        card_ids = {
            str(row.get("id", "")).replace("cluster-", "", 1)
            for row in cards
        }
        if expected_clusters:
            if not card_ids:
                _fail("major_questlines has no cluster cards despite v3 quest clusters")
            if not card_ids.issubset(expected_clusters):
                _fail(
                    "major_questlines cards reference unknown cluster ids "
                    f"(got {sorted(card_ids)}, expected subset of {sorted(expected_clusters)})"
                )
            if not card_ids.intersection(expected_clusters):
                _fail(
                    "major_questlines cards do not align with v3 cluster ids "
                    f"(expected one of {sorted(expected_clusters)}, got {sorted(card_ids)})"
                )

    evidence_path = run_root / "data" / "evidence" / "evidence_packs.jsonl"
    if evidence_path.exists():
        zone_evidence_rows: list[dict[str, Any]] = []
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            build_meta = row.get("build_meta") or {}
            subject_zone = str(build_meta.get("subject_zone_id", row.get("subject_id", "")))
            if subject_zone not in {"", resolved_zone_id}:
                continue
            zone_evidence_rows.append(row)

        eligible_history_blocks = 0
        covered_clusters: set[str] = set()
        glance_items = 0
        eligible_faction_candidates: set[str] = set()
        faction_ids_with_profile: set[str] = set()
        faction_names_by_id: dict[str, str] = {}
        for row in zone_evidence_rows:
            field_name = str(row.get("field_name", ""))
            build_meta = row.get("build_meta") or {}
            if field_name == "history_digest":
                eligible_history_blocks += len(row.get("evidence_items", []))
            elif field_name == "quest_cluster_lore":
                cluster_id = str(build_meta.get("cluster_id", "")).strip()
                if cluster_id:
                    covered_clusters.add(cluster_id)
            elif field_name == "at_a_glance_input":
                glance_items += len(row.get("evidence_items", []))
            elif field_name == "faction_pool":
                faction_id = str(build_meta.get("faction_id", "")).strip()
                if faction_id:
                    eligible_faction_candidates.add(faction_id)
                    faction_ids_with_profile.add(faction_id)
                    faction_name = str(build_meta.get("faction_name", "")).strip()
                    if faction_name:
                        faction_names_by_id[faction_id] = faction_name
        targets_path = run_root / "data" / "discovery" / "faction_profile_targets.json"
        if targets_path.exists():
            targets_blob = _load_json(targets_path)
            if isinstance(targets_blob, list):
                for row in targets_blob:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("zone_id", "")).strip() != resolved_zone_id:
                        continue
                    faction_id = str(row.get("faction_id", "")).strip()
                    faction_name = str(row.get("name", "")).strip()
                    if faction_id:
                        eligible_faction_candidates.add(faction_id)
                        if faction_name:
                            faction_names_by_id.setdefault(faction_id, faction_name)
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            card_name = str(card.get("name", "")).strip()
            if card_id and card_name:
                faction_names_by_id.setdefault(card_id, card_name)

        def _seed_mentions_for_faction(faction_id: str) -> list[dict[str, Any]]:
            faction_name = faction_names_by_id.get(faction_id, "").strip()
            if not faction_name:
                return []
            mentions: list[dict[str, Any]] = []
            for row in zone_evidence_rows:
                field_name = str(row.get("field_name", ""))
                if field_name not in {"history_digest", "currently_input", "questline_pool", "at_a_glance_input"}:
                    continue
                build_meta = row.get("build_meta") or {}
                for item in row.get("evidence_items", []):
                    if not isinstance(item, dict):
                        continue
                    snippet = str(item.get("snippet", "")).strip()
                    if not snippet:
                        continue
                    if re.search(rf"\b{re.escape(faction_name)}\b", snippet, re.IGNORECASE):
                        mentions.append(
                            {
                                "snippet": snippet,
                                "section_role": str(item.get("section_role", build_meta.get("section_role", ""))),
                                "field_name": field_name,
                            }
                        )
            return mentions
        if len(eligible_faction_candidates) >= MIN_FACTION_CARDS and len(faction_cards) < MIN_FACTION_CARDS:
            _fail(
                f"major_factions count {len(faction_cards)} below minimum {MIN_FACTION_CARDS} "
                f"for {len(eligible_faction_candidates)} faction candidates"
            )
        draft_faction_ids = {str(card.get("id", "")).strip() for card in faction_cards}
        unknown_ids = sorted(draft_faction_ids - eligible_faction_candidates)
        if unknown_ids and eligible_faction_candidates:
            _fail(
                "major_factions cards reference unknown faction ids "
                f"(got {unknown_ids}, expected subset of {sorted(eligible_faction_candidates)})"
            )
        provenance = draft.get("provenance") or {}
        faction_provenance = provenance.get("major_factions") or {}
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            if card_id in faction_ids_with_profile and card_id not in faction_provenance:
                _fail(f"major_factions card missing provenance despite profile evidence: {card_id!r}")
        for card in faction_cards:
            card_id = str(card.get("id", "")).strip()
            if card_id not in {"faction-alliance", "faction-horde"}:
                continue
            binding_count = 0
            if v3_rows:
                binding = "alliance" if card_id == "faction-alliance" else "horde"
                binding_count = sum(
                    1
                    for row in v3_rows
                    if isinstance(row, dict)
                    and str(row.get("zone_id", "")) == resolved_zone_id
                    and str(row.get("node_type", "")) == "quest"
                    and str(row.get("faction_binding", "")).strip().lower() == binding
                )
            seed_mentions = _seed_mentions_for_faction(card_id)
            if not alliance_horde_conflict_met(
                faction_id=card_id,
                quest_binding_count=binding_count,
                seed_mentions=seed_mentions,
            ):
                print(
                    f"WARN: {card_id!r} present in major_factions without strong conflict signal "
                    "(quest bindings or high-weight seed mention)"
                )
        if eligible_history_blocks >= MIN_HISTORY_SECTIONS and len(history) < MIN_HISTORY_SECTIONS:
            _fail(
                f"history_sections count {len(history)} below minimum {MIN_HISTORY_SECTIONS} "
                f"for {eligible_history_blocks} seed history blocks"
            )
        if v3_rows:
            expected_clusters = _cluster_ids_from_v3(v3_rows, resolved_zone_id)
            missing = sorted(expected_clusters - covered_clusters)
            if expected_clusters and missing:
                _fail(f"clusters missing quest_cluster_lore evidence: {missing}")
        if glance_items > 50:
            _fail(f"at_a_glance_input pool exceeds cap: {glance_items}")

        source_kind_by_id: dict[str, str] = {}
        for row in zone_evidence_rows:
            build_meta = row.get("build_meta") or {}
            source_id = str(build_meta.get("source_id", "")).strip()
            source_kind = str(build_meta.get("source_kind", "")).strip()
            if source_id and source_kind:
                source_kind_by_id[source_id] = source_kind
        provenance = draft.get("provenance") or {}
        for field_name in ("at_a_glance", "currently", "history"):
            for pointer in provenance.get(field_name, []):
                if not isinstance(pointer, dict):
                    continue
                source_id = str(pointer.get("source_id", "")).strip()
                source_kind = source_kind_by_id.get(source_id, "")
                if source_kind and source_kind != "seed":
                    print(
                        f"WARN: {field_name} provenance references non-seed source "
                        f"{source_id!r} (source_kind={source_kind!r})"
                    )

    traversal_path = run_root / "data" / "ingest" / "traversal_report.json"
    if traversal_path.exists():
        traversal_blob = _load_json(traversal_path)
        if isinstance(traversal_blob, dict):
            for entry in traversal_blob.get("entries", []):
                if not isinstance(entry, dict):
                    continue
                if entry.get("role") != "quest" or entry.get("status") != "fetched":
                    continue
                link = str(entry.get("link", "")).strip()
                if not link:
                    continue
                if str(entry.get("traversal_origin", "")).strip() == "hub_resolved":
                    if not str(entry.get("hub_resolved_from", "")).strip():
                        _fail(f"hub_resolved quest fetch missing hub_resolved_from: {link!r}")
                valid, reasons = is_valid_quest_graph_link(link, zone_name=zone_name)
                if not valid:
                    _fail(f"traversal report fetched denylisted quest href: {link!r} ({reasons})")

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
    try:
        check_run(args.run_root, zone_id=args.zone_id)
    except SemanticCheckError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
