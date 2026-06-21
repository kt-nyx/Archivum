"""Post-traversal discovery enrich pass: rebuild graphs, decisions, and evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.common.wiki_evidence_filters import should_exclude_from_history
from pipeline.contracts.models import (
    DecisionArtifact,
    EvidencePack,
    QuestlineClusterSummary,
    QuestRecord,
)
from pipeline.discovery.instance_bosses import is_boss_section_role
from pipeline.discovery.location_discovery import (
    build_location_decision_row,
    build_zone_seed_text,
)
from pipeline.discovery.quest_lore import extract_quest_lore
from pipeline.discovery.quest_roster import build_quest_roster
from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata
from pipeline.discovery.questline_cluster import apply_cluster_layers, cluster_zone_questlines
from pipeline.discovery.questline_significance import (
    load_included_cluster_ids_by_zone,
    score_zone_questline_clusters,
)
from pipeline.discovery.storyline_html import parse_storyline_html, v3_to_legacy_v1
from pipeline.discovery.workflow import _load_json, _section_role

# "roster" (pre-traverse): build the flat, UNCLUSTERED quest graph + zone-level
# questline decision; clustering is deferred until quest pages exist (Slice B).
# "full" keeps the legacy single-pass clustering behavior for any direct callers.
EnrichPhase = Literal["full", "roster", "cluster", "significance", "card_polish", "evidence_merge"]

_UNCLUSTERED_CLUSTER_ID = "unclustered"

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


def _instance_seed_field_names(
    section_role: str, *, lead_emitted: int, block_type: str = "paragraph"
) -> list[str]:
    lowered = section_role.lower()
    names: list[str] = []
    # Prose-oriented fields only draw from paragraph text. List/table blocks (added
    # so rosters reach boss_pool + structured links) are not narrative prose and
    # must not pollute at_a_glance / history with loot/quest/patch/roster fragments.
    is_prose = block_type == "paragraph"
    if is_prose and lowered in {"lead", "introduction"} and lead_emitted < 2:
        names.append("at_a_glance_input")
    if is_prose and _is_history_digest_role(lowered):
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


def _seed_field_names(
    section_role: str, *, lead_emitted: int, block_type: str = "paragraph"
) -> list[str]:
    lowered = section_role.lower()
    names: list[str] = []
    # Zone prose fields draw from paragraphs only; list/table blocks (subregion,
    # loot, quest, resource lists) are not prose and historically never reached
    # these fields, so keep them out to avoid evidence bloat/dilution.
    if block_type != "paragraph":
        return names
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
    included_clusters_by_zone: dict[str, set[str]] | None = None,
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
            quest_node_id = str(
                snapshot.get("quest_node_id", snapshot.get("auxiliary_target_id", ""))
            ).strip()
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
                            "section_role": _section_role(
                                str(snippet_row.get("section_role", "other"))
                            ),
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
                zone_included = (included_clusters_by_zone or {}).get(subject_id)
                if zone_included is not None and cluster_id not in zone_included:
                    continue
                cluster_snippets.setdefault((subject_id, cluster_id), []).append(pack)
            continue

        block_index = 0
        for block in section_blocks:
            if not isinstance(block, dict):
                continue
            raw_section = str(block.get("section_role", ""))
            role = _section_role(raw_section)
            block_type = str(block.get("block_type", "paragraph"))
            snippet = clean_wiki_snippet(str(block.get("text", "")))
            if not snippet:
                continue
            block_index += 1

            if is_zone_seed:
                lead_emitted = lead_counts.get(subject_id, 0)
                field_names = _seed_field_names(
                    raw_section, lead_emitted=lead_emitted, block_type=block_type
                )
                if "at_a_glance_input" in field_names and raw_section.lower() in {
                    "lead",
                    "introduction",
                }:
                    lead_counts[subject_id] = lead_emitted + 1
                if not field_names:
                    continue
            elif is_instance_seed:
                lead_emitted = lead_counts.get(subject_id, 0)
                field_names = _instance_seed_field_names(
                    raw_section, lead_emitted=lead_emitted, block_type=block_type
                )
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
            elif aux_role in {"parent_lore", "related_lore"}:
                # Cross-page lore is the highest overreach risk, so use a strict narrative
                # allowlist (lead/intro + history/lore/background/story) rather than the
                # broad _is_history_digest_role denylist used for instance-owned prose.
                lowered_raw = raw_section.lower()
                is_narrative = lowered_raw in {"lead", "introduction"} or any(
                    token in lowered_raw for token in ("history", "lore", "background", "story")
                )
                if lowered_raw.startswith("in_the_rpg") or not is_narrative:
                    continue
                field_names = [
                    "parent_lore_pool" if aux_role == "parent_lore" else "related_lore_pool"
                ]
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
                    build_meta["instance_id"] = str(
                        snapshot.get("auxiliary_target_id", subject_id)
                    ).strip()
                if is_instance_seed or aux_role == "instance_lore":
                    build_meta["lore_scope"] = "instance"
                elif aux_role == "parent_lore":
                    build_meta["lore_scope"] = "parent"
                    build_meta["lore_source_title"] = page_title or entity_name
                elif aux_role == "related_lore":
                    build_meta["lore_scope"] = "related"
                    build_meta["lore_source_title"] = page_title or entity_name
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
        zone_included = (included_clusters_by_zone or {}).get(subject_id)
        if zone_included is not None and cluster_id not in zone_included:
            continue
        for pack in cluster_packs:
            key = _pack_key(pack)
            if key in seen_cluster_keys:
                continue
            seen_cluster_keys.add(key)
            existing_build_meta = pack.get("build_meta")
            cluster_pack = {
                "subject_id": subject_id,
                "subject_type": "zone",
                "field_name": "quest_cluster_lore",
                "evidence_items": list(pack.get("evidence_items", [])),
                "constraints": pack.get("constraints", {}),
                "build_meta": {
                    **(existing_build_meta if isinstance(existing_build_meta, dict) else {}),
                    "cluster_id": cluster_id,
                },
            }
            packs.append(cluster_pack)
    return packs


def _load_or_aggregate_quest_records(
    discovery_dir: Path,
    snapshots: list[dict[str, Any]],
) -> tuple[Path, list[dict[str, Any]]]:
    """Load quest_records.jsonl from traverse, or aggregate from quest snapshots."""
    quest_records_path = discovery_dir / "quest_records.jsonl"
    records: list[dict[str, Any]] = []
    if quest_records_path.exists():
        for line in quest_records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    records.append(row)
    if not records:
        seen_links: set[str] = set()
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("auxiliary_role", "")).strip() != "quest":
                continue
            raw = snapshot.get("quest_record")
            if not isinstance(raw, dict) or not raw.get("has_questbox", True):
                continue
            link_key = str(raw.get("source_link", "")).strip().lower().split("#", 1)[0]
            if link_key and link_key in seen_links:
                continue
            if link_key:
                seen_links.add(link_key)
            records.append(raw)
    validated = [QuestRecord.model_validate(row).model_dump(mode="json") for row in records]
    if validated and not quest_records_path.exists():
        quest_records_path.write_text(
            "\n".join(json.dumps(row) for row in validated) + "\n",
            encoding="utf-8",
        )
    return quest_records_path, validated


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
    missing = [
        cluster_id
        for zone_id, cluster_id in sorted(clusters)
        if (zone_id, cluster_id) not in covered
    ]
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
        "zone_quest_clusters": discovery_dir / "zone_quest_clusters.json",
        "zone_quest_cluster_rankings": discovery_dir / "zone_quest_cluster_rankings.json",
        "zone_questline_card_metadata": discovery_dir / "zone_questline_card_metadata.json",
        "location_significance_decisions": decisions_dir / "location_significance_decisions.json",
        "questline_inclusion_decisions": decisions_dir / "questline_inclusion_decisions.json",
        "evidence_packs": evidence_dir / "evidence_packs.jsonl",
        "enrich_report": discovery_dir / "discovery_enrich_report.json",
    }

    if phase == "cluster":
        v3_blob = _load_json(outputs["zone_quest_graph_v3"])
        questline_graph_v3 = v3_blob if isinstance(v3_blob, list) else []
        quest_records_path, quest_records = _load_or_aggregate_quest_records(
            discovery_dir, snapshots
        )
        storyline_by_zone = _storyline_snapshots_by_zone(snapshots)
        zone_names: dict[str, str] = {}
        for snapshot in snapshots:
            if isinstance(snapshot, dict) and _is_seed_snapshot(snapshot):
                zone_names[str(snapshot.get("entity_id", ""))] = str(snapshot.get("name", ""))

        records_by_zone: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in quest_records:
            zone_id = str(record.get("zone_id", "")).strip()
            if zone_id:
                records_by_zone[zone_id].append(record)

        rows_by_zone: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in questline_graph_v3:
            if isinstance(row, dict):
                zone_id = str(row.get("zone_id", "")).strip()
                if zone_id:
                    rows_by_zone[zone_id].append(row)

        clustered_rows: list[dict[str, Any]] = []
        cluster_summaries: list[dict[str, Any]] = []
        max_cluster_size = 0
        unresolved_edge_count = 0
        for zone_id in sorted(set(rows_by_zone) | set(records_by_zone)):
            zone_rows, summaries, zone_unresolved = cluster_zone_questlines(
                zone_id=zone_id,
                roster_rows=rows_by_zone.get(zone_id, []),
                quest_records=records_by_zone.get(zone_id, []),
                storyline_html=str(storyline_by_zone.get(zone_id, {}).get("parse_html", "")),
                zone_name=zone_names.get(zone_id, ""),
            )
            clustered_rows.extend(zone_rows)
            cluster_summaries.extend(summaries)
            unresolved_edge_count += zone_unresolved
            for summary in summaries:
                max_cluster_size = max(max_cluster_size, int(summary.get("quest_count", 0)))

        quest_graph = v3_to_legacy_v1(clustered_rows)
        write_json(outputs["zone_quest_graph"], quest_graph)
        write_json(outputs["zone_quest_graph_v3"], clustered_rows)
        write_json(outputs["zone_quest_clusters"], cluster_summaries)
        cluster_ids = {
            (str(row.get("zone_id", "")), str(row.get("cluster_id", "")))
            for row in clustered_rows
            if row.get("cluster_id")
        }
        prior_report = _load_json(outputs["enrich_report"])
        report_payload = prior_report if isinstance(prior_report, dict) else {}
        report_payload.update(
            {
                "run_id": context.run_id,
                "enrich_phase": phase,
                "snapshot_count": len(snapshots),
                "quest_record_count": len(quest_records),
                "v3_quest_count": sum(
                    1 for row in clustered_rows if row.get("node_type") == "quest"
                ),
                "v3_cluster_count": len(cluster_ids),
                "max_cluster_quest_count": max_cluster_size,
                "unresolved_edge_count": unresolved_edge_count,
                "quest_records_path": str(quest_records_path),
            }
        )
        write_json(outputs["enrich_report"], report_payload)
        outputs["quest_records"] = quest_records_path
        for row in cluster_summaries:
            QuestlineClusterSummary.model_validate(row)
        return outputs

    if phase == "significance":
        v3_blob = _load_json(outputs["zone_quest_graph_v3"])
        questline_graph_v3 = v3_blob if isinstance(v3_blob, list) else []
        clusters_blob = _load_json(outputs["zone_quest_clusters"])
        cluster_summaries = clusters_blob if isinstance(clusters_blob, list) else []
        quest_records_path, quest_records = _load_or_aggregate_quest_records(
            discovery_dir, snapshots
        )
        storyline_by_zone = _storyline_snapshots_by_zone(snapshots)

        all_decisions: list[dict[str, Any]] = []
        all_rankings: list[dict[str, Any]] = []
        included_total = 0
        excluded_total = 0
        borderline_total = 0

        summaries_by_zone: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for summary in cluster_summaries:
            if isinstance(summary, dict):
                zone_id = str(summary.get("zone_id", "")).strip()
                if zone_id:
                    summaries_by_zone[zone_id].append(summary)

        for zone_id in sorted(summaries_by_zone):
            zone_rows = [
                row for row in questline_graph_v3 if str(row.get("zone_id", "")) == zone_id
            ]
            decisions, ranking = score_zone_questline_clusters(
                zone_id=zone_id,
                cluster_summaries=summaries_by_zone[zone_id],
                v3_rows=zone_rows,
                quest_records=quest_records,
                seed_text=build_zone_seed_text(snapshots, zone_id),
                storyline_html=str(storyline_by_zone.get(zone_id, {}).get("parse_html", "")),
                run_id=context.run_id,
            )
            all_decisions.extend(decisions)
            all_rankings.append(ranking)
            for row in decisions:
                if str(row.get("subject_type", "")) != "questline_cluster":
                    continue
                decision = str(row.get("final_decision", ""))
                if decision == "include":
                    included_total += 1
                elif decision == "exclude":
                    excluded_total += 1
                if row.get("borderline_adjudication"):
                    borderline_total += 1

        write_json(outputs["questline_inclusion_decisions"], all_decisions)
        write_json(outputs["zone_quest_cluster_rankings"], all_rankings)
        for row in all_decisions:
            DecisionArtifact.model_validate(row)

        prior_report = _load_json(outputs["enrich_report"])
        report_payload = prior_report if isinstance(prior_report, dict) else {}
        report_payload.update(
            {
                "run_id": context.run_id,
                "enrich_phase": phase,
                "quest_record_count": len(quest_records),
                "clusters_scored": sum(
                    1 for row in all_decisions if row.get("subject_type") == "questline_cluster"
                ),
                "clusters_included": included_total,
                "clusters_excluded": excluded_total,
                "clusters_borderline": borderline_total,
                "quest_records_path": str(quest_records_path),
            }
        )
        write_json(outputs["enrich_report"], report_payload)
        outputs["quest_records"] = quest_records_path
        return outputs

    if phase == "card_polish":
        v3_blob = _load_json(outputs["zone_quest_graph_v3"])
        questline_graph_v3 = v3_blob if isinstance(v3_blob, list) else []
        clusters_blob = _load_json(outputs["zone_quest_clusters"])
        cluster_summaries = clusters_blob if isinstance(clusters_blob, list) else []
        rankings_blob = _load_json(outputs["zone_quest_cluster_rankings"])
        rankings_list = rankings_blob if isinstance(rankings_blob, list) else []
        included_by_zone = load_included_cluster_ids_by_zone(rankings_list)
        quest_records_path, quest_records = _load_or_aggregate_quest_records(
            discovery_dir, snapshots
        )

        metadata_rows: list[dict[str, Any]] = []
        aggregate_metrics: dict[str, int] = defaultdict(int)
        summaries_by_zone = defaultdict(list)
        for summary in cluster_summaries:
            if isinstance(summary, dict):
                zone_id = str(summary.get("zone_id", "")).strip()
                if zone_id:
                    summaries_by_zone[zone_id].append(summary)

        for zone_id in sorted(included_by_zone):
            zone_rows = [
                row for row in questline_graph_v3 if str(row.get("zone_id", "")) == zone_id
            ]
            rows, metrics = build_zone_questline_card_metadata(
                zone_id=zone_id,
                cluster_summaries=summaries_by_zone.get(zone_id, []),
                v3_rows=zone_rows,
                quest_records=quest_records,
                included_cluster_ids=included_by_zone[zone_id],
            )
            metadata_rows.extend(rows)
            for key, value in metrics.items():
                aggregate_metrics[key] += int(value)

        write_json(outputs["zone_questline_card_metadata"], metadata_rows)
        prior_report = _load_json(outputs["enrich_report"])
        report_payload = prior_report if isinstance(prior_report, dict) else {}
        report_payload.update(
            {
                "run_id": context.run_id,
                "enrich_phase": phase,
                "quest_record_count": len(quest_records),
                "card_polish_cluster_count": aggregate_metrics.get("card_polish_cluster_count", 0),
                "card_polish_registry_mapped_count": aggregate_metrics.get(
                    "card_polish_registry_mapped_count", 0
                ),
                "card_polish_entry_anchor_count": aggregate_metrics.get(
                    "card_polish_entry_anchor_count", 0
                ),
                "card_polish_unmapped_count": aggregate_metrics.get(
                    "card_polish_unmapped_count", 0
                ),
                "quest_records_path": str(quest_records_path),
            }
        )
        write_json(outputs["enrich_report"], report_payload)
        outputs["quest_records"] = quest_records_path
        return outputs

    if phase == "evidence_merge":
        v3_blob = _load_json(outputs["zone_quest_graph_v3"])
        questline_graph_v3 = v3_blob if isinstance(v3_blob, list) else []
        rankings_blob = _load_json(outputs["zone_quest_cluster_rankings"])
        rankings_list = rankings_blob if isinstance(rankings_blob, list) else []
        included_by_zone = load_included_cluster_ids_by_zone(rankings_list)
        included_sets = {
            zone_id: set(cluster_ids) for zone_id, cluster_ids in included_by_zone.items()
        }
        evidence_packs = _build_evidence_packs(
            snapshots,
            context.run_id,
            v3_rows=questline_graph_v3,
            included_clusters_by_zone=included_sets or None,
        )
        clusters_with_evidence, clusters_missing = _cluster_evidence_metrics(
            questline_graph_v3, evidence_packs
        )
        quest_records_path, quest_records = _load_or_aggregate_quest_records(
            discovery_dir, snapshots
        )
        all_cluster_ids = {
            (str(row.get("zone_id", "")), str(row.get("cluster_id", "")))
            for row in questline_graph_v3
            if row.get("cluster_id")
        }
        included_cluster_keys = {
            (zone_id, cluster_id)
            for zone_id, cluster_ids in included_by_zone.items()
            for cluster_id in cluster_ids
        }
        prior_report = _load_json(outputs["enrich_report"])
        report_payload = prior_report if isinstance(prior_report, dict) else {}
        report_payload.update(
            {
                "run_id": context.run_id,
                "enrich_phase": phase,
                "snapshot_count": len(snapshots),
                "evidence_pack_count": len(evidence_packs),
                "quest_record_count": len(quest_records),
                "clusters_with_quest_evidence": clusters_with_evidence,
                "clusters_missing_evidence": clusters_missing,
                "clusters_included_for_evidence": len(included_cluster_keys),
                "clusters_excluded_from_evidence": len(all_cluster_ids - included_cluster_keys),
            }
        )
        outputs["evidence_packs"].write_text(
            "\n".join(json.dumps(row) for row in evidence_packs) + "\n", encoding="utf-8"
        )
        write_json(outputs["enrich_report"], report_payload)
        outputs["quest_records"] = quest_records_path
        for row in evidence_packs:
            EvidencePack.model_validate(row)
        return outputs

    location_candidates = _load_json(discovery_dir / "zone_location_candidates.json")
    if not isinstance(location_candidates, list):
        location_candidates = []

    questline_graph_v3 = []
    location_decisions: list[dict[str, Any]] = []
    questline_decisions: list[dict[str, Any]] = []
    storyline_by_zone = _storyline_snapshots_by_zone(snapshots)
    storyline_parse_status: dict[str, str] = {}

    zone_names = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if _is_seed_snapshot(snapshot):
            zone_names[str(snapshot.get("entity_id", ""))] = str(snapshot.get("name", ""))

    for zone_id in sorted(set(zone_names) | set(storyline_by_zone)):
        storyline_snap = storyline_by_zone.get(zone_id)
        parse_html = str(storyline_snap.get("parse_html", "")) if storyline_snap else ""
        zone_name = zone_names.get(zone_id, "")
        if phase == "roster":
            # Flat, unclustered roster: storyline links + Category:<Zone> quests
            # fallback. Clustering is deferred to Slice B (post-traverse).
            v3_rows = build_quest_roster(
                zone_id=zone_id,
                zone_name=zone_name,
                storyline_html=parse_html,
            )
        else:
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
        zone_id: build_zone_seed_text(snapshots, zone_id) for zone_id in sorted(zone_names)
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
        zone_cluster_ids = {
            str(row.get("cluster_id", "")) for row in zone_v3 if row.get("cluster_id")
        }
        part_count = len(zone_cluster_ids)
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
                    "include"
                    if score >= 0.7 or quest_count >= 3
                    else ("defer" if borderline else "exclude")
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

    evidence_packs = []
    if phase in {"full", "roster"}:
        evidence_packs = _build_evidence_packs(
            snapshots, context.run_id, v3_rows=questline_graph_v3
        )
    history_digest_count = sum(
        1 for row in evidence_packs if row.get("field_name") == "history_digest"
    )
    v3_quest_count = sum(1 for row in questline_graph_v3 if row.get("node_type") == "quest")
    v3_cluster_count = len(
        {
            (str(row.get("zone_id", "")), str(row.get("cluster_id", "")))
            for row in questline_graph_v3
            if row.get("cluster_id")
        }
    )
    clusters_with_evidence, clusters_missing = _cluster_evidence_metrics(
        questline_graph_v3, evidence_packs
    )

    write_json(outputs["zone_quest_graph"], quest_graph)
    write_json(outputs["zone_quest_graph_v3"], questline_graph_v3)
    write_json(outputs["location_significance_decisions"], location_decisions)
    write_json(outputs["questline_inclusion_decisions"], questline_decisions)
    if phase in {"full", "roster"}:
        outputs["evidence_packs"].write_text(
            "\n".join(json.dumps(row) for row in evidence_packs) + "\n", encoding="utf-8"
        )
    write_json(
        outputs["enrich_report"],
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
    )

    for row in location_decisions + questline_decisions:
        DecisionArtifact.model_validate(row)
    for row in evidence_packs:
        EvidencePack.model_validate(row)
    return outputs
