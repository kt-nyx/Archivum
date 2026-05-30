"""Post-traversal discovery enrich pass: rebuild graphs, decisions, and evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pipeline.common.run_context import RunContext
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.common.wiki_evidence_filters import should_exclude_from_history
from pipeline.contracts.models import DecisionArtifact, EvidencePack
from pipeline.discovery.quest_lore import extract_quest_lore
from pipeline.discovery.location_discovery import (
    build_location_decision_row,
    build_zone_seed_text,
)
from pipeline.discovery.instance_bosses import is_boss_section_role
from pipeline.discovery.questline_clustering import apply_cluster_layers
from pipeline.discovery.storyline_html import parse_storyline_html, v3_to_legacy_v1
from pipeline.discovery.workflow import _load_json, _section_role

EnrichPhase = Literal["full", "graph_only", "evidence_merge"]

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


def _is_instance_seed_snapshot(snapshot: dict[str, Any]) -> bool:
    return (
        str(snapshot.get("entity_type", "")) == "instance"
        and not str(snapshot.get("auxiliary_role", "")).strip()
    )


def _instance_seed_field_names(section_role: str, *, lead_emitted: int) -> list[str]:
    lowered = section_role.lower()
    names: list[str] = []
    if lowered in {"lead", "introduction"} and lead_emitted < 2:
        names.append("at_a_glance_input")
    if _is_history_digest_role(lowered):
        names.append("history_digest")
        names.append("at_a_glance_input")
    if is_boss_section_role(section_role):
        names.append("boss_pool")
    return names


def _is_history_digest_role(section_role: str) -> bool:
    lowered = section_role.lower()
    if lowered.startswith("in_the_rpg"):
        return False
    if lowered in _HISTORY_DIGEST_EXCLUDED:
        return False
    if "history" in lowered:
        return True
    if lowered.endswith("_edit"):
        return True
    return False


def _is_currently_input_role(section_role: str) -> bool:
    lowered = section_role.lower()
    if lowered.startswith("in_the_rpg"):
        return False
    if lowered in {"quests_edit", "quests", "quests_or_storyline"}:
        return True
    if lowered in _HISTORY_DIGEST_EXCLUDED:
        return False
    if lowered.endswith("_edit"):
        return True
    return False


_GEOGRAPHY_INPUT_HINTS = ("maps", "subregion", "geography")


def _is_geography_input_role(section_role: str) -> bool:
    lowered = section_role.lower()
    if lowered.startswith("in_the_rpg"):
        return False
    if lowered in {"geography_edit", "geography", "maps_subregions"}:
        return True
    return any(hint in lowered for hint in _GEOGRAPHY_INPUT_HINTS)


def _seed_field_names(section_role: str, *, lead_emitted: int) -> list[str]:
    lowered = section_role.lower()
    names: list[str] = []
    if lowered in {"lead", "introduction"} and lead_emitted < 2:
        names.append("at_a_glance_input")
    if _is_geography_input_role(lowered):
        names.append("geography_input")
    if _is_history_digest_role(lowered):
        names.append("history_digest")
        names.append("at_a_glance_input")
    if _is_currently_input_role(lowered):
        names.append("currently_input")
    return names


def _pack_key(row: dict[str, Any]) -> tuple[str, ...]:
    meta = row.get("build_meta") or {}
    return (
        str(row.get("subject_id", "")),
        str(row.get("field_name", "")),
        str(meta.get("source_id", "")),
        str(meta.get("cluster_id", "")),
        str(meta.get("quest_node_id", "")),
        str((row.get("evidence_items") or [{}])[0].get("snippet", ""))[:80],
    )


def _normalize_wiki_link_key(url_or_link: str) -> str:
    value = str(url_or_link).strip().lower().split("#", 1)[0]
    if "/wiki/" in value:
        return value[value.index("/wiki/") :]
    return value


def _v3_cluster_index(v3_rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in v3_rows:
        if not isinstance(row, dict) or row.get("node_type") != "quest":
            continue
        zone_id = str(row.get("zone_id", "")).strip()
        source_link = _normalize_wiki_link_key(str(row.get("source_link", "")))
        node_id = str(row.get("node_id", "")).strip()
        cluster_id = str(row.get("cluster_id", "")).strip()
        if zone_id and source_link:
            index[f"{zone_id}|{source_link}"] = {
                "cluster_id": cluster_id,
                "quest_node_id": node_id,
            }
        if zone_id and node_id:
            index[f"{zone_id}|node|{node_id}"] = {
                "cluster_id": cluster_id,
                "quest_node_id": node_id,
            }
    return index


def _build_evidence_packs(
    snapshots: list[dict[str, Any]],
    run_id: str,
    *,
    v3_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    lead_counts: dict[str, int] = {}
    cluster_index = _v3_cluster_index(v3_rows or [])
    cluster_snippets: dict[tuple[str, str], list[dict[str, Any]]] = {}

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
        is_zone_seed = _is_seed_snapshot(snapshot)
        is_instance_seed = _is_instance_seed_snapshot(snapshot)
        is_seed = is_zone_seed or is_instance_seed
        source_kind = "seed" if is_seed else "auxiliary"
        subject_zone_id = subject_id
        section_blocks = snapshot.get("section_blocks", [])
        if not isinstance(section_blocks, list):
            section_blocks = []

        if aux_role == "quest":
            lore_blocks = snapshot.get("quest_lore_blocks", [])
            if not isinstance(lore_blocks, list) or not lore_blocks:
                lore_blocks = extract_quest_lore(section_blocks)
            quest_node_id = str(snapshot.get("quest_node_id", snapshot.get("auxiliary_target_id", ""))).strip()
            link_key = f"{subject_id}|{_normalize_wiki_link_key(wiki_url)}"
            index_meta = cluster_index.get(link_key) or cluster_index.get(
                f"{subject_id}|node|{quest_node_id}", {}
            )
            cluster_id = str(index_meta.get("cluster_id", "")).strip()
            if not cluster_id:
                cluster_id = str(snapshot.get("cluster_id", "")).strip()
            quest_node_id = quest_node_id or str(index_meta.get("quest_node_id", "")).strip()
            for snippet_row in lore_blocks:
                if not isinstance(snippet_row, dict):
                    continue
                snippet = clean_wiki_snippet(str(snippet_row.get("text", "")))
                if not snippet:
                    continue
                pack = {
                    "subject_id": subject_id,
                    "subject_type": entity_type,
                    "field_name": "quest_lore",
                    "evidence_items": [
                        {
                            "source_url": wiki_url,
                            "source_title": page_title or entity_name,
                            "snippet": snippet,
                            "section_role": _section_role(str(snippet_row.get("section_role", "other"))),
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
                        "cluster_id": cluster_id,
                        "quest_node_id": quest_node_id,
                        "page_title": page_title,
                    },
                }
                packs.append(pack)
                if cluster_id:
                    cluster_snippets.setdefault((subject_id, cluster_id), []).append(pack)
            continue

        block_index = 0
        for block in section_blocks:
            if not isinstance(block, dict):
                continue
            raw_section = str(block.get("section_role", ""))
            role = _section_role(raw_section)
            snippet = clean_wiki_snippet(str(block.get("text", "")))
            if not snippet:
                continue
            block_index += 1

            if is_zone_seed:
                lead_emitted = lead_counts.get(subject_id, 0)
                field_names = _seed_field_names(raw_section, lead_emitted=lead_emitted)
                if "at_a_glance_input" in field_names and raw_section.lower() in {
                    "lead",
                    "introduction",
                }:
                    lead_counts[subject_id] = lead_emitted + 1
                if not field_names:
                    continue
            elif is_instance_seed:
                lead_emitted = lead_counts.get(subject_id, 0)
                field_names = _instance_seed_field_names(raw_section, lead_emitted=lead_emitted)
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
            elif aux_role == "instance_lore":
                field_names = ["instance_lore_pool"]
            else:
                continue

            for field_name in field_names:
                exclude_history = should_exclude_from_history(
                    {
                        "snippet": snippet,
                        "raw_section_role": raw_section,
                        "section_role": role,
                    }
                )
                if field_name == "history_digest" and exclude_history:
                    continue
                if field_name == "geography_input" and exclude_history:
                    continue
                if (
                    field_name == "at_a_glance_input"
                    and _is_history_digest_role(raw_section)
                    and exclude_history
                ):
                    continue

                build_meta: dict[str, Any] = {
                    "run_id": run_id,
                    "source_id": source_id,
                    "phase": "enrich",
                    "source_kind": source_kind,
                    "auxiliary_role": aux_role,
                    "subject_zone_id": subject_zone_id,
                    "section_role": role,
                    "raw_section_role": raw_section,
                    "block_index": str(block_index),
                }
                if aux_role == "faction_profile":
                    build_meta["faction_id"] = str(snapshot.get("auxiliary_target_id", "")).strip()
                    build_meta["faction_name"] = page_title or entity_name
                if aux_role == "location_profile":
                    build_meta["location_id"] = str(snapshot.get("auxiliary_target_id", "")).strip()
                    build_meta["location_name"] = page_title or entity_name
                if aux_role == "instance_lore":
                    build_meta["instance_id"] = str(snapshot.get("auxiliary_target_id", subject_id)).strip()
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
                                "raw_section_role": raw_section,
                                "block_index": block_index,
                                "confidence": 1.0,
                            }
                        ],
                        "constraints": {"max_tokens": 1200, "forbidden_extrapolation": True},
                        "build_meta": build_meta,
                    }
                )

    seen_cluster_keys: set[tuple[str, ...]] = set()
    for (subject_id, cluster_id), cluster_packs in sorted(cluster_snippets.items()):
        for pack in cluster_packs:
            key = _pack_key(pack)
            if key in seen_cluster_keys:
                continue
            seen_cluster_keys.add(key)
            cluster_pack = {
                "subject_id": subject_id,
                "subject_type": "zone",
                "field_name": "quest_cluster_lore",
                "evidence_items": list(pack.get("evidence_items", [])),
                "constraints": pack.get("constraints", {}),
                "build_meta": {
                    **(pack.get("build_meta") or {}),
                    "cluster_id": cluster_id,
                },
            }
            packs.append(cluster_pack)
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


def _cluster_evidence_metrics(
    v3_rows: list[dict[str, Any]],
    evidence_packs: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    clusters = {
        (str(row.get("zone_id", "")), str(row.get("cluster_id", "")))
        for row in v3_rows
        if isinstance(row, dict) and row.get("cluster_id")
    }
    covered: set[tuple[str, str]] = set()
    for pack in evidence_packs:
        if pack.get("field_name") != "quest_cluster_lore":
            continue
        meta = pack.get("build_meta") or {}
        zone_id = str(meta.get("subject_zone_id", pack.get("subject_id", ""))).strip()
        cluster_id = str(meta.get("cluster_id", "")).strip()
        if zone_id and cluster_id:
            covered.add((zone_id, cluster_id))
    missing = [cluster_id for zone_id, cluster_id in sorted(clusters) if (zone_id, cluster_id) not in covered]
    return len(covered), missing


def run_discovery_enrich(
    context: RunContext,
    source_manifest_path: Path,
    *,
    phase: EnrichPhase = "full",
) -> dict[str, Path]:
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

    outputs = {
        "zone_quest_graph": discovery_dir / "zone_quest_graph.json",
        "zone_quest_graph_v3": discovery_dir / "zone_quest_graph_v3.json",
        "location_significance_decisions": decisions_dir / "location_significance_decisions.json",
        "questline_inclusion_decisions": decisions_dir / "questline_inclusion_decisions.json",
        "evidence_packs": evidence_dir / "evidence_packs.jsonl",
        "enrich_report": discovery_dir / "discovery_enrich_report.json",
    }

    if phase == "evidence_merge":
        v3_blob = _load_json(outputs["zone_quest_graph_v3"])
        questline_graph_v3 = v3_blob if isinstance(v3_blob, list) else []
        evidence_packs = _build_evidence_packs(snapshots, context.run_id, v3_rows=questline_graph_v3)
        clusters_with_evidence, clusters_missing = _cluster_evidence_metrics(questline_graph_v3, evidence_packs)
        prior_report = _load_json(outputs["enrich_report"])
        report_payload = prior_report if isinstance(prior_report, dict) else {}
        report_payload.update(
            {
                "run_id": context.run_id,
                "enrich_phase": phase,
                "snapshot_count": len(snapshots),
                "evidence_pack_count": len(evidence_packs),
                "clusters_with_quest_evidence": clusters_with_evidence,
                "clusters_missing_evidence": clusters_missing,
            }
        )
        outputs["evidence_packs"].write_text(
            "\n".join(json.dumps(row) for row in evidence_packs) + "\n", encoding="utf-8"
        )
        outputs["enrich_report"].write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        for row in evidence_packs:
            EvidencePack.model_validate(row)
        return outputs

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
            v3_rows = apply_cluster_layers(v3_rows, html=parse_html)
        if v3_rows:
            storyline_parse_status[zone_id] = "ok"
        elif parse_html.strip():
            storyline_parse_status[zone_id] = "empty"
        else:
            storyline_parse_status[zone_id] = "missing_html"
        questline_graph_v3.extend(v3_rows)

    quest_graph = v3_to_legacy_v1(questline_graph_v3)

    zone_seed_text_by_id = {
        zone_id: build_zone_seed_text(snapshots, zone_id)
        for zone_id in sorted(zone_names)
    }
    for candidate in location_candidates:
        if not isinstance(candidate, dict):
            continue
        zone_id = str(candidate.get("zone_id", "")).strip()
        location_decisions.append(
            build_location_decision_row(
                candidate,
                run_id=context.run_id,
                algorithm_version="v2-enrich",
                seed_text=zone_seed_text_by_id.get(zone_id, ""),
            )
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

    evidence_packs: list[dict[str, Any]] = []
    if phase in {"full", "graph_only"}:
        evidence_packs = _build_evidence_packs(snapshots, context.run_id, v3_rows=questline_graph_v3)
    history_digest_count = sum(1 for row in evidence_packs if row.get("field_name") == "history_digest")
    v3_quest_count = sum(1 for row in questline_graph_v3 if row.get("node_type") == "quest")
    v3_cluster_count = len(
        {
            (str(row.get("zone_id", "")), str(row.get("cluster_id", "")))
            for row in questline_graph_v3
            if row.get("cluster_id")
        }
    )
    clusters_with_evidence, clusters_missing = _cluster_evidence_metrics(questline_graph_v3, evidence_packs)

    outputs["zone_quest_graph"].write_text(json.dumps(quest_graph, indent=2), encoding="utf-8")
    outputs["zone_quest_graph_v3"].write_text(json.dumps(questline_graph_v3, indent=2), encoding="utf-8")
    outputs["location_significance_decisions"].write_text(
        json.dumps(location_decisions, indent=2), encoding="utf-8"
    )
    outputs["questline_inclusion_decisions"].write_text(
        json.dumps(questline_decisions, indent=2), encoding="utf-8"
    )
    if phase in {"full", "graph_only"}:
        outputs["evidence_packs"].write_text(
            "\n".join(json.dumps(row) for row in evidence_packs) + "\n", encoding="utf-8"
        )
    outputs["enrich_report"].write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "enrich_phase": phase,
                "snapshot_count": len(snapshots),
                "evidence_pack_count": len(evidence_packs),
                "quest_graph_nodes": len(questline_graph_v3),
                "v3_quest_count": v3_quest_count,
                "v3_cluster_count": v3_cluster_count,
                "history_digest_block_count": history_digest_count,
                "storyline_parse_status": storyline_parse_status,
                "storyline_zones": sorted(storyline_by_zone.keys()),
                "clusters_with_quest_evidence": clusters_with_evidence,
                "clusters_missing_evidence": clusters_missing,
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
