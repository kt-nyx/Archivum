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
from pipeline.generate.draft.wiki_first import build_instance_page, build_zone_page

# Re-export for tests that patch chat_json_completion on this module.
__all__ = [
    "chat_json_completion",
    "draft_chat_json_completion",
    "run_draft_writer",
    "set_draft_verbose",
]


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
    questline_decisions_path = context.data_dir / "decisions" / "questline_inclusion_decisions.json"
    if questline_decisions_path.exists():
        blob = json.loads(questline_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            for row in blob:
                if not isinstance(row, dict):
                    continue
                subject_id = str(row.get("subject_id", "")).strip()
                if subject_id:
                    questline_decision_map[subject_id] = row
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

    def _write(path: Path) -> tuple[Path | None, dict[str, object] | None]:
        fact_pack = json.loads(path.read_text(encoding="utf-8"))
        entity_type = str(fact_pack.get("entity_type", ""))
        entity_id = str(fact_pack.get("entity_id", path.stem))
        if entity_type in {"zone", "instance"} and evidence_rows:
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
                snapshots_path = context.data_dir / "ingest" / "source_snapshots.json"
                if snapshots_path.exists():
                    snapshots_blob = json.loads(snapshots_path.read_text(encoding="utf-8"))
                    if isinstance(snapshots_blob, list):
                        for snapshot in snapshots_blob:
                            if not isinstance(snapshot, dict):
                                continue
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
                )
            entity_dir = stage_dir / f"{entity_type}_page"
            entity_dir.mkdir(parents=True, exist_ok=True)
            out_path = entity_dir / f"{entity_id}.json"
            out_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
            decision = {
                "entity_id": entity_id,
                "entity_type": f"{entity_type}_page",
                "generation_mode": "deterministic_evidence_pack",
                "schema_repair_applied": "no",
                "prompt_profile": "wiki_first_v1",
            }
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
    with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
        futures = [executor.submit(_write, path) for path in fact_pack_paths]
        for future in futures:
            output_path, decision = future.result()
            if output_path is not None:
                outputs.append(output_path)
            if decision is not None:
                decisions.append(decision)
    (stage_dir / "draft_decisions.json").write_text(
        json.dumps(decisions, indent=2),
        encoding="utf-8",
    )
    return outputs
