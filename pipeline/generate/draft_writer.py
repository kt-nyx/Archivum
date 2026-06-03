"""Draft stage implementation for policy-compliant canonical JSON outputs."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.common.run_context import RunContext
from pipeline.generate.draft import generate_entity_draft, is_valid_draft
from pipeline.generate.draft.llm import draft_chat_json_completion, set_draft_verbose
from pipeline.generate.draft.mode import draft_pipeline_mode
from pipeline.generate.draft.trace import DraftTraceContext
from pipeline.discovery.questline_significance import load_included_cluster_ids_by_zone
from pipeline.generate.draft.wiki_first import (
    build_instance_key_character_roster,
    build_instance_page,
    build_zone_page,
)

# Re-export for tests that patch chat_json_completion on this module.
__all__ = [
    "chat_json_completion",
    "draft_chat_json_completion",
    "run_draft_writer",
    "set_draft_verbose",
]


def _decision_name_key(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _build_key_character_decision_row(
    *,
    instance_id: str,
    instance_name: str,
    scoped_evidence: list[dict[str, Any]],
    parent_zone_evidence: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]] | None,
    snapshots: list[dict[str, Any]],
    emitted_cards: list,
) -> dict[str, Any]:
    """Decision sidecar row: the full ranked roster + which candidates were emitted.

    Uses the same deterministic roster builder as ``build_instance_page`` so the
    role-diversity check in ``check_run_semantics`` keys off the identical candidate set.
    """
    roster = build_instance_key_character_roster(
        instance_id=instance_id,
        instance_name=instance_name,
        evidence_rows=scoped_evidence,
        section_blocks=section_blocks,
        snapshots=snapshots,
        parent_zone_evidence_rows=parent_zone_evidence,
    )
    emitted_keys = {
        _decision_name_key(card.get("name", ""))
        for card in emitted_cards
        if isinstance(card, dict)
    }
    candidates = [
        {
            "name": candidate.name,
            "role": candidate.role or "uncertain",
            "significance": getattr(candidate, "significance", None),
            "emitted": _decision_name_key(candidate.name) in emitted_keys,
        }
        for candidate in roster
    ]
    return {"instance_id": instance_id, "candidates": candidates}


def run_draft_writer(
    context: RunContext,
    fact_pack_paths: list[Path],
    *,
    max_entity_concurrency: int = 4,
    verbose: bool = False,
) -> list[Path]:
    """Write canonical entity drafts from extracted fact packs."""
    set_draft_verbose(verbose)
    stage_dir = context.data_dir / "drafts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    trace_path = stage_dir / "draft_llm_trace.jsonl"
    pipeline_mode = draft_pipeline_mode()

    prompt_profiles = {
        "zone": "draft_zone_v2_staged" if pipeline_mode == "staged" else "draft_zone_v1",
        "instance": "draft_instance_v1",
        "sub_zone": (
            "draft_sub_zone_v2_staged" if pipeline_mode == "staged" else "draft_sub_zone_v1"
        ),
        "character": "draft_character_v1",
        "glossary_term": "draft_glossary_term_v1",
        "asset": "draft_asset_v1",
    }
    evidence_rows: list[dict[str, Any]] = []
    evidence_path = context.data_dir / "evidence" / "evidence_packs.jsonl"
    if evidence_path.exists():
        evidence_rows = [
            json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    quest_graph_v3_rows: list[dict[str, Any]] = []
    quest_graph_v3_path = context.data_dir / "discovery" / "zone_quest_graph_v3.json"
    if quest_graph_v3_path.exists():
        blob = json.loads(quest_graph_v3_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            quest_graph_v3_rows = [row for row in blob if isinstance(row, dict)]
    instance_lore_rows: list[dict[str, Any]] = []
    lore_map_path = context.data_dir / "discovery" / "instance_lore_source_map.json"
    if lore_map_path.exists():
        blob = json.loads(lore_map_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            instance_lore_rows = [row for row in blob if isinstance(row, dict)]
    location_rows: list[dict[str, Any]] = []
    location_rows_path = context.data_dir / "discovery" / "zone_location_classification.json"
    if location_rows_path.exists():
        blob = json.loads(location_rows_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            location_rows = [row for row in blob if isinstance(row, dict)]
    instance_rows: list[dict[str, Any]] = []
    instance_rows_path = context.data_dir / "discovery" / "zone_instance_registry.json"
    if instance_rows_path.exists():
        blob = json.loads(instance_rows_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            instance_rows = [row for row in blob if isinstance(row, dict)]
    location_candidate_map: dict[str, dict[str, Any]] = {}
    location_candidates_path = context.data_dir / "discovery" / "zone_location_candidates.json"
    if location_candidates_path.exists():
        blob = json.loads(location_candidates_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            for row in blob:
                if not isinstance(row, dict):
                    continue
                location_id = str(row.get("location_id", "")).strip()
                if not location_id:
                    continue
                location_candidate_map[location_id] = row
    location_decision_map: dict[str, dict[str, Any]] = {}
    location_decisions_path = context.data_dir / "decisions" / "location_significance_decisions.json"
    if location_decisions_path.exists():
        blob = json.loads(location_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            for row in blob:
                if not isinstance(row, dict):
                    continue
                subject_id = str(row.get("subject_id", "")).strip()
                if subject_id:
                    location_decision_map[subject_id] = row
    questline_decision_map: dict[str, dict[str, Any]] = {}
    questline_cluster_decision_map: dict[str, dict[str, Any]] = {}
    cluster_rankings_by_zone: dict[str, list[str]] = {}
    questline_decisions_path = context.data_dir / "decisions" / "questline_inclusion_decisions.json"
    if questline_decisions_path.exists():
        blob = json.loads(questline_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            for row in blob:
                if not isinstance(row, dict):
                    continue
                subject_type = str(row.get("subject_type", "")).strip()
                subject_id = str(row.get("subject_id", "")).strip()
                if subject_type == "zone_questline_set" and subject_id:
                    questline_decision_map[subject_id] = row
                elif subject_type == "questline_cluster" and subject_id:
                    questline_cluster_decision_map[subject_id] = row
    rankings_path = context.data_dir / "discovery" / "zone_quest_cluster_rankings.json"
    if rankings_path.exists():
        rankings_blob = json.loads(rankings_path.read_text(encoding="utf-8"))
        if isinstance(rankings_blob, list):
            cluster_rankings_by_zone = load_included_cluster_ids_by_zone(rankings_blob)
    faction_profile_targets: list[dict[str, Any]] = []
    faction_targets_path = context.data_dir / "discovery" / "faction_profile_targets.json"
    if faction_targets_path.exists():
        targets_blob = json.loads(faction_targets_path.read_text(encoding="utf-8"))
        if isinstance(targets_blob, list):
            faction_profile_targets = [row for row in targets_blob if isinstance(row, dict)]
    location_profile_targets: list[dict[str, Any]] = []
    location_targets_path = context.data_dir / "discovery" / "location_profile_targets.json"
    if location_targets_path.exists():
        targets_blob = json.loads(location_targets_path.read_text(encoding="utf-8"))
        if isinstance(targets_blob, list):
            location_profile_targets = [row for row in targets_blob if isinstance(row, dict)]
    source_snapshots: list[dict[str, Any]] = []
    snapshots_path = context.data_dir / "ingest" / "source_snapshots.json"
    if snapshots_path.exists():
        snapshots_blob = json.loads(snapshots_path.read_text(encoding="utf-8"))
        if isinstance(snapshots_blob, list):
            source_snapshots = [row for row in snapshots_blob if isinstance(row, dict)]

    def _write(path: Path) -> tuple[Path | None, dict[str, object] | None]:
        fact_pack = json.loads(path.read_text(encoding="utf-8"))
        entity_type = str(fact_pack.get("entity_type", ""))
        entity_id = str(fact_pack.get("entity_id", path.stem))
        if entity_type in {"zone", "instance"} and evidence_rows:
            instance_key_character_decisions: dict[str, Any] | None = None
            scoped_evidence = [
                row for row in evidence_rows if str(row.get("subject_id", "")).strip() == entity_id
            ]
            if entity_type == "zone":
                scoped_quest_rows = [
                    row
                    for row in quest_graph_v3_rows
                    if row.get("zone_id") == entity_id and str(row.get("node_type", "")) == "quest"
                ]
                scoped_location_rows = [
                    row for row in location_rows if str(row.get("zone_id", "")).strip() == entity_id
                ]
                draft = build_zone_page(
                    fact_pack,
                    scoped_evidence,
                    scoped_quest_rows,
                    scoped_location_rows,
                    instance_rows,
                    location_candidate_map,
                    location_decision_map,
                    questline_decision_map.get(entity_id),
                    questline_cluster_decision_map=questline_cluster_decision_map,
                    included_cluster_ids=cluster_rankings_by_zone.get(entity_id),
                    faction_profile_targets=[
                        row
                        for row in faction_profile_targets
                        if str(row.get("zone_id", "")).strip() == entity_id
                    ],
                    location_profile_targets=[
                        row
                        for row in location_profile_targets
                        if str(row.get("zone_id", "")).strip() == entity_id
                    ],
                    snapshots=source_snapshots,
                )
            else:
                lore_source = next(
                    (row for row in instance_lore_rows if str(row.get("instance_id", "")).strip() == entity_id),
                    None,
                )
                parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
                parent_zone_evidence = [
                    row
                    for row in evidence_rows
                    if str(row.get("subject_id", "")).strip() == parent_zone_id
                ] if parent_zone_id else []
                parent_zone_name = ""
                if parent_zone_id:
                    parent_fact_path = path.parent / f"{parent_zone_id}.json"
                    if parent_fact_path.exists():
                        parent_fact = json.loads(parent_fact_path.read_text(encoding="utf-8"))
                        parent_zone_name = str(parent_fact.get("name", "")).strip()
                enriched_fact_pack = {
                    **fact_pack,
                    "parent_zone_name": parent_zone_name,
                }
                instance_section_blocks: list[dict[str, Any]] | None = None
                if source_snapshots:
                    for snapshot in source_snapshots:
                        if (
                            str(snapshot.get("entity_id", "")).strip() == entity_id
                            and str(snapshot.get("entity_type", "")).strip() == "instance"
                            and not str(snapshot.get("auxiliary_role", "")).strip()
                        ):
                            blocks = snapshot.get("section_blocks", [])
                            if isinstance(blocks, list):
                                instance_section_blocks = [row for row in blocks if isinstance(row, dict)]
                            break
                draft = build_instance_page(
                    enriched_fact_pack,
                    scoped_evidence,
                    lore_source,
                    parent_zone_evidence_rows=parent_zone_evidence,
                    faction_profile_targets=faction_profile_targets,
                    section_blocks=instance_section_blocks,
                    snapshots=source_snapshots,
                )
                # Mirror build_instance_page's input resolution exactly so the sidecar roster
                # is identical to the roster the page assembly used (name string + section
                # blocks fallback to the fact pack when no instance snapshot was found).
                roster_section_blocks = (
                    instance_section_blocks
                    if instance_section_blocks is not None
                    else enriched_fact_pack.get("section_blocks", [])
                )
                instance_key_character_decisions = _build_key_character_decision_row(
                    instance_id=entity_id,
                    instance_name=str(enriched_fact_pack.get("name", entity_id)),
                    scoped_evidence=scoped_evidence,
                    parent_zone_evidence=parent_zone_evidence,
                    section_blocks=roster_section_blocks,
                    snapshots=source_snapshots,
                    emitted_cards=draft.get("key_characters", []),
                )
            entity_dir = stage_dir / f"{entity_type}_page"
            entity_dir.mkdir(parents=True, exist_ok=True)
            out_path = entity_dir / f"{entity_id}.json"
            overflow = draft.pop("draft_overflow_decisions", None)
            out_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
            decision = {
                "entity_id": entity_id,
                "entity_type": f"{entity_type}_page",
                "generation_mode": "deterministic_evidence_pack",
                "schema_repair_applied": "no",
                "prompt_profile": "wiki_first_v1",
            }
            if isinstance(overflow, list):
                decision["questline_overflow"] = overflow
            if instance_key_character_decisions is not None:
                decision["instance_key_character_decisions"] = instance_key_character_decisions
            return out_path, decision
        settings = load_ai_settings()
        trace = DraftTraceContext(
            entity_id=entity_id,
            pipeline_mode=pipeline_mode,
            trace_path=trace_path,
        )
        attempts = 3
        mode = "openai"
        draft: dict[str, Any] | None = None
        used_schema_retry = False
        for attempt in range(1, attempts + 1):
            draft, mode = generate_entity_draft(
                fact_pack,
                entity_type,
                context=context,
                trace=trace,
            )
            if is_valid_draft(entity_type, draft):
                break
            used_schema_retry = True
            if attempt == attempts:
                raise RuntimeError(
                    f"draft for entity '{entity_id}' is invalid after "
                    f"{attempts} schema-guarded attempts"
                )
        if draft is None:  # pragma: no cover
            raise RuntimeError(f"draft generation returned no payload for '{entity_id}'")
        entity_dir = stage_dir / entity_type
        entity_dir.mkdir(parents=True, exist_ok=True)
        out_path = entity_dir / f"{draft['id']}.json"
        out_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        decision: dict[str, object] = {
            "entity_id": str(draft["id"]),
            "entity_type": entity_type,
            "generation_mode": mode,
            "coalesce_mode": str(fact_pack.get("coalesce_mode", "unknown")),
            "schema_repair_applied": "yes" if used_schema_retry else "no",
            "ai_provider": getattr(settings, "provider", "openai"),
            "ai_model": settings.openai_model,
            "prompt_profile": prompt_profiles.get(entity_type, "draft_unknown"),
        }
        decision.update(trace.decision_metadata())
        return out_path, decision

    outputs: list[Path] = []
    decisions: list[dict[str, object]] = []
    instance_key_character_decisions: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [executor.submit(_write, path) for path in fact_pack_paths]
        for future in futures:
            output_path, decision = future.result()
            if output_path is not None:
                outputs.append(output_path)
            if decision is not None:
                kc_decision = decision.pop("instance_key_character_decisions", None)
                if isinstance(kc_decision, dict):
                    instance_key_character_decisions.append(kc_decision)
                decisions.append(decision)
                overflow = decision.pop("questline_overflow", None)
                if isinstance(overflow, list):
                    for row in overflow:
                        if isinstance(row, dict):
                            decisions.append(
                                {
                                    "entity_id": str(row.get("entity_id", decision.get("entity_id", ""))),
                                    "entity_type": str(row.get("entity_type", "questline_cluster")),
                                    "generation_mode": "deterministic_evidence_pack",
                                    "reason": str(row.get("reason", "questline_overflow")),
                                    "cluster_id": str(row.get("cluster_id", "")),
                                }
                            )
    (stage_dir / "draft_decisions.json").write_text(
        json.dumps(decisions, indent=2),
        encoding="utf-8",
    )
    decisions_dir = context.data_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "instance_key_character_decisions.json").write_text(
        json.dumps(instance_key_character_decisions, indent=2),
        encoding="utf-8",
    )
    return outputs
