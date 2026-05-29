"""Post-traversal discovery enrich pass: rebuild graphs, decisions, and evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.contracts.models import DecisionArtifact, EvidencePack
from pipeline.discovery.storyline_html import parse_storyline_html, v3_to_legacy_v1
from pipeline.discovery.storyline_parser import _to_entity_id
from pipeline.discovery.workflow import (
    _HARD_REJECT_MARKERS,
    _LOCATION_INCLUDE_SECTION_WEIGHTS,
    _load_json,
    _section_role,
)

_HISTORY_DIGEST_EXCLUDED = frozenset(
    {
        "geography_edit",
        "geography",
        "quests_edit",
        "quests",
        "getting_there_edit",
        "getting_there",
        "resources_edit",
        "resources",
        "in_the_rpg_edit",
        "in_the_rpg",
        "maps_subregions",
    }
)


def _is_seed_snapshot(snapshot: dict[str, Any]) -> bool:
    return (
        str(snapshot.get("entity_type", "")) == "zone"
        and not str(snapshot.get("auxiliary_role", "")).strip()
    )


def _is_history_digest_role(section_role: str) -> bool:
    lowered = section_role.lower()
    if lowered in _HISTORY_DIGEST_EXCLUDED:
        return False
    if "history" in lowered:
        return True
    if lowered.endswith("_edit"):
        return True
    return False


def _is_currently_input_role(section_role: str) -> bool:
    lowered = section_role.lower()
    if lowered in {"quests_edit", "quests", "quests_or_storyline"}:
        return True
    if lowered in _HISTORY_DIGEST_EXCLUDED:
        return False
    if lowered.endswith("_edit"):
        return True
    return False


def _seed_field_names(section_role: str, *, lead_emitted: int) -> list[str]:
    """Return scoped prose field names for a zone seed section block."""
    lowered = section_role.lower()
    names: list[str] = []
    if lowered in {"lead", "introduction"} and lead_emitted < 2:
        names.append("at_a_glance_input")
    if _is_history_digest_role(lowered):
        names.append("history_digest")
        names.append("at_a_glance_input")
    if _is_currently_input_role(lowered):
        names.append("currently_input")
    return names


def _build_evidence_packs(snapshots: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    lead_counts: dict[str, int] = {}

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        subject_id = str(snapshot.get("entity_id", "")).strip()
        entity_type = str(snapshot.get("entity_type", "")).strip()
        source_id = str(snapshot.get("source_id", "")).strip()
        wiki_url = str(snapshot.get("url", ""))
        entity_name = str(snapshot.get("name", "")).strip()
        aux_role = str(snapshot.get("auxiliary_role", "")).strip()
        page_title = str(snapshot.get("page_title", entity_name)).strip()
        is_seed = _is_seed_snapshot(snapshot)
        source_kind = "seed" if is_seed else "auxiliary"
        subject_zone_id = subject_id
        section_blocks = snapshot.get("section_blocks", [])
        if not isinstance(section_blocks, list):
            section_blocks = []

        for block in section_blocks:
            if not isinstance(block, dict):
                continue
            raw_section = str(block.get("section_role", ""))
            role = _section_role(raw_section)
            snippet = clean_wiki_snippet(str(block.get("text", "")))
            if not snippet:
                continue

            if is_seed:
                lead_emitted = lead_counts.get(subject_id, 0)
                field_names = _seed_field_names(raw_section, lead_emitted=lead_emitted)
                if "at_a_glance_input" in field_names and raw_section.lower() in {
                    "lead",
                    "introduction",
                }:
                    lead_counts[subject_id] = lead_emitted + 1
                if not field_names:
                    continue
            elif aux_role == "storyline":
                field_names = ["questline_pool"]
            elif aux_role == "faction_profile":
                field_names = ["faction_pool"]
            elif aux_role == "location_profile":
                field_names = ["location_pool"]
            elif aux_role == "quest":
                field_names = ["questline_pool"]
            else:
                continue

            for field_name in field_names:
                packs.append(
                    {
                        "subject_id": subject_id,
                        "subject_type": entity_type,
                        "field_name": field_name,
                        "evidence_items": [
                            {
                                "source_url": wiki_url,
                                "source_title": page_title or entity_name,
                                "snippet": snippet,
                                "section_role": role,
                                "confidence": 1.0,
                            }
                        ],
                        "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
                        "build_meta": {
                            "run_id": run_id,
                            "source_id": source_id,
                            "phase": "enrich",
                            "source_kind": source_kind,
                            "auxiliary_role": aux_role,
                            "subject_zone_id": subject_zone_id,
                        },
                    }
                )
    return packs


def _storyline_snapshots_by_zone(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_zone: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("auxiliary_role", "")).strip() != "storyline":
            continue
        zone_id = str(snapshot.get("entity_id", "")).strip()
        if zone_id:
            by_zone[zone_id] = snapshot
    return by_zone


def run_discovery_enrich(context: RunContext, source_manifest_path: Path) -> dict[str, Path]:
    """Rebuild quest graphs, inclusion decisions, and evidence from full snapshot set."""
    _ = source_manifest_path
    snapshots_path = context.stage_dir("ingest") / "source_snapshots.json"
    snapshots = _load_json(snapshots_path)
    if not isinstance(snapshots, list):
        raise RuntimeError("source_snapshots.json must be a JSON array")

    discovery_dir = context.data_dir / "discovery"
    decisions_dir = context.data_dir / "decisions"
    evidence_dir = context.data_dir / "evidence"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    location_candidates = _load_json(discovery_dir / "zone_location_candidates.json")
    if not isinstance(location_candidates, list):
        location_candidates = []

    questline_graph_v3: list[dict[str, Any]] = []
    location_decisions: list[dict[str, Any]] = []
    questline_decisions: list[dict[str, Any]] = []
    storyline_by_zone = _storyline_snapshots_by_zone(snapshots)
    storyline_parse_status: dict[str, str] = {}

    zone_names: dict[str, str] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if _is_seed_snapshot(snapshot):
            zone_names[str(snapshot.get("entity_id", ""))] = str(snapshot.get("name", ""))

    for zone_id, storyline_snap in storyline_by_zone.items():
        parse_html = str(storyline_snap.get("parse_html", ""))
        zone_name = zone_names.get(zone_id, "")
        v3_rows = parse_storyline_html(parse_html, zone_id=zone_id, zone_name=zone_name)
        if v3_rows:
            storyline_parse_status[zone_id] = "ok"
        elif parse_html.strip():
            storyline_parse_status[zone_id] = "empty"
        else:
            storyline_parse_status[zone_id] = "missing_html"
        questline_graph_v3.extend(v3_rows)

    quest_graph = v3_to_legacy_v1(questline_graph_v3)

    for candidate in location_candidates:
        if not isinstance(candidate, dict):
            continue
        name_lowered = str(candidate.get("name", "")).lower()
        hard_reject_reasons = [m for m in _HARD_REJECT_MARKERS if m in name_lowered]
        source_section_role = str(candidate.get("source_section_role", "other"))
        if hard_reject_reasons:
            location_class = "reject"
        elif "city" in name_lowered:
            location_class = "city"
        elif "starter" in name_lowered:
            location_class = "starter_area"
        else:
            location_class = "major_location_candidate"
        base_score = 0.15
        if location_class in {"city", "starter_area"}:
            base_score += 0.6
        else:
            base_score += 0.25
        base_score += _LOCATION_INCLUDE_SECTION_WEIGHTS.get(source_section_role, 0.0)
        if any(marker in name_lowered for marker in ("classic", "warcraft rpg", "novel", "novella")):
            base_score -= 0.35
        if len(name_lowered.split()) <= 1:
            base_score -= 0.1
        score = max(0.0, min(1.0, base_score))
        borderline = 0.45 <= score <= 0.65
        location_decisions.append(
            {
                "subject_id": candidate["location_id"],
                "subject_type": "location",
                "run_id": context.run_id,
                "algorithm_version": "v2-enrich",
                "features": {
                    "keyword_density": 1 if score > 0.6 else 0,
                    "has_hard_reject": bool(hard_reject_reasons),
                    "source_section_role": source_section_role,
                },
                "hard_reject": bool(hard_reject_reasons),
                "hard_reject_reasons": hard_reject_reasons,
                "score": score,
                "thresholds": {"include_min": 0.7, "borderline_min": 0.45, "borderline_max": 0.65},
                "borderline_adjudication": (
                    {
                        "prompt_class": "location_significance_borderline",
                        "ruling": "include" if score >= 0.5 else "exclude",
                    }
                    if borderline
                    else None
                ),
                "final_decision": "exclude" if hard_reject_reasons else ("include" if score >= 0.7 else "defer"),
                "reason_codes": (
                    ["hard_reject"]
                    if hard_reject_reasons
                    else ["score_based", f"source_role:{source_section_role}"]
                ),
            }
        )

    for zone_id in sorted(set(zone_names) | set(storyline_by_zone)):
        zone_v3 = [row for row in questline_graph_v3 if str(row.get("zone_id", "")) == zone_id]
        quest_count = sum(1 for row in zone_v3 if row.get("node_type") == "quest")
        cluster_ids = {str(row.get("cluster_id", "")) for row in zone_v3 if row.get("cluster_id")}
        part_count = len(cluster_ids)
        depth = len(zone_v3)
        score = min(1.0, (part_count * 0.15) + (quest_count * 0.05) + (0.3 if depth >= 3 else 0.0))
        borderline = 0.45 <= score <= 0.65
        questline_decisions.append(
            {
                "subject_id": zone_id,
                "subject_type": "zone_questline_set",
                "run_id": context.run_id,
                "algorithm_version": "v3-enrich",
                "features": {
                    "quest_graph_depth": depth,
                    "part_count": part_count,
                    "quest_count": quest_count,
                    "has_storyline_page": zone_id in storyline_by_zone,
                    "storyline_parse_status": storyline_parse_status.get(zone_id, "missing"),
                },
                "hard_reject": False,
                "hard_reject_reasons": [],
                "score": score,
                "thresholds": {"include_min": 0.7, "borderline_min": 0.45, "borderline_max": 0.65},
                "borderline_adjudication": (
                    {
                        "prompt_class": "questline_inclusion_borderline",
                        "ruling": "include" if quest_count >= 2 else "exclude",
                    }
                    if borderline
                    else None
                ),
                "final_decision": (
                    "include" if score >= 0.7 or quest_count >= 3 else ("defer" if borderline else "exclude")
                ),
                "reason_codes": ["storyline_page", "graph_depth"],
            }
        )

    existing_questline = _load_json(decisions_dir / "questline_inclusion_decisions.json")
    if isinstance(existing_questline, list):
        enriched_zone_ids = {str(row.get("subject_id", "")) for row in questline_decisions}
        for row in existing_questline:
            if isinstance(row, dict) and str(row.get("subject_id", "")) not in enriched_zone_ids:
                questline_decisions.append(row)

    evidence_packs = _build_evidence_packs(snapshots, context.run_id)
    history_digest_count = sum(1 for row in evidence_packs if row.get("field_name") == "history_digest")
    v3_quest_count = sum(1 for row in questline_graph_v3 if row.get("node_type") == "quest")
    v3_cluster_count = len(
        {
            (str(row.get("zone_id", "")), str(row.get("cluster_id", "")))
            for row in questline_graph_v3
            if row.get("cluster_id")
        }
    )

    outputs = {
        "zone_quest_graph": discovery_dir / "zone_quest_graph.json",
        "zone_quest_graph_v3": discovery_dir / "zone_quest_graph_v3.json",
        "location_significance_decisions": decisions_dir / "location_significance_decisions.json",
        "questline_inclusion_decisions": decisions_dir / "questline_inclusion_decisions.json",
        "evidence_packs": evidence_dir / "evidence_packs.jsonl",
        "enrich_report": discovery_dir / "discovery_enrich_report.json",
    }
    outputs["zone_quest_graph"].write_text(json.dumps(quest_graph, indent=2), encoding="utf-8")
    outputs["zone_quest_graph_v3"].write_text(json.dumps(questline_graph_v3, indent=2), encoding="utf-8")
    outputs["location_significance_decisions"].write_text(
        json.dumps(location_decisions, indent=2), encoding="utf-8"
    )
    outputs["questline_inclusion_decisions"].write_text(
        json.dumps(questline_decisions, indent=2), encoding="utf-8"
    )
    outputs["evidence_packs"].write_text(
        "\n".join(json.dumps(row) for row in evidence_packs) + "\n", encoding="utf-8"
    )
    outputs["enrich_report"].write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "snapshot_count": len(snapshots),
                "evidence_pack_count": len(evidence_packs),
                "quest_graph_nodes": len(questline_graph_v3),
                "v3_quest_count": v3_quest_count,
                "v3_cluster_count": v3_cluster_count,
                "history_digest_block_count": history_digest_count,
                "storyline_parse_status": storyline_parse_status,
                "storyline_zones": sorted(storyline_by_zone.keys()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    for row in location_decisions + questline_decisions:
        DecisionArtifact.model_validate(row)
    for row in evidence_packs:
        EvidencePack.model_validate(row)
    return outputs
