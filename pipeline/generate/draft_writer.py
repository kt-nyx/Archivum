"""Draft stage implementation for policy-compliant canonical JSON outputs."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.ai.openai_client import chat_json_completion
from pipeline.common.io import write_json
from pipeline.common.run_context import RunContext
from pipeline.common.text_normalize import normalize_display_payload
from pipeline.discovery.instance_bosses import classify_character_role
from pipeline.discovery.questline_card_polish import load_questline_card_metadata
from pipeline.discovery.questline_significance import load_included_cluster_ids_by_zone
from pipeline.generate.draft import finalize_trace, generate_entity_draft, is_valid_draft
from pipeline.generate.draft.llm import draft_chat_json_completion, set_draft_verbose
from pipeline.generate.draft.mode import draft_pipeline_mode
from pipeline.generate.draft.pages import (
    InstanceKeyCharacterSelection,
    build_instance_page,
    build_zone_page,
)
from pipeline.generate.draft.temporal import enrich_evidence_temporal_metadata
from pipeline.generate.draft.trace import DraftTraceContext

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
    selection: InstanceKeyCharacterSelection,
    emitted_cards: list,
) -> dict[str, Any]:
    """Decision sidecar: full prefiltered pool + merge ranks for emitted cast.

    The ``selection`` is the *same* object ``build_instance_page`` emitted the cast from, so
    the sidecar merge ranks always agree with the page (no second, divergent LLM pass).
    List order is emitted-first (merge order), then offline-ranked remainder; the first
    INSTANCE_MAX_KEY_CHARACTERS entries are the role-diversity window for assess_role_diversity.
    """
    emitted_keys = {
        _decision_name_key(card.get("name", "")) for card in emitted_cards if isinstance(card, dict)
    }
    merge_rank_by_name = {
        candidate.name: index for index, candidate in enumerate(selection.cast, start=1)
    }
    candidates = []
    for candidate in selection.pool:
        emitted = _decision_name_key(candidate.name) in emitted_keys
        role = candidate.role or "uncertain"
        if role == "uncertain":
            role, _reason = classify_character_role(candidate, instance_name=instance_name)
        row = {
            "name": candidate.name,
            "role": role,
            "emitted": emitted,
            "merge_rank": merge_rank_by_name.get(candidate.name) if emitted else None,
            "selection_reason": selection.selection_reasons.get(candidate.name)
            if emitted
            else None,
        }
        candidates.append(row)
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
            json.loads(line)
            for line in evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
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
    location_decisions_path = (
        context.data_dir / "decisions" / "location_significance_decisions.json"
    )
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
    card_metadata_by_cluster = load_questline_card_metadata(
        context.data_dir / "discovery" / "zone_questline_card_metadata.json"
    )
    quest_descriptions_by_node: dict[str, str] = {}
    quest_records_by_node: dict[str, dict[str, Any]] = {}
    quest_records_path = context.data_dir / "discovery" / "quest_records.jsonl"
    if quest_records_path.exists():
        for line in quest_records_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            node_id = str(row.get("node_id", "")).strip()
            if node_id:
                quest_records_by_node[node_id] = row
            description = str(
                row.get("description")
                or row.get("quest_description")
                or row.get("objectives_text")
                or ""
            ).strip()
            if node_id and description:
                quest_descriptions_by_node[node_id] = description
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

    fact_packs_by_entity: dict[str, dict[str, Any]] = {}
    for fact_path in fact_pack_paths:
        if not fact_path.exists():
            continue
        fact_pack = json.loads(fact_path.read_text(encoding="utf-8"))
        if isinstance(fact_pack, dict):
            entity_id = str(fact_pack.get("entity_id", fact_path.stem)).strip()
            if entity_id:
                fact_packs_by_entity[entity_id] = fact_pack
    temporal_decisions: list[dict[str, Any]] = []
    entry_state_contract_decisions: list[dict[str, Any]] = []
    content_boundary_decisions: list[dict[str, Any]] = []
    canonical_temporal_decisions: list[dict[str, Any]] = []
    if evidence_rows:
        (
            evidence_rows,
            temporal_decisions,
            entry_state_contract_decisions,
            content_boundary_decisions,
            canonical_temporal_decisions,
        ) = enrich_evidence_temporal_metadata(
            evidence_rows,
            fact_packs_by_entity=fact_packs_by_entity,
            source_snapshots=source_snapshots,
            questline_card_metadata=card_metadata_by_cluster,
            quest_records_by_node=quest_records_by_node,
            run_id=context.run_id,
            return_entry_state_contract_decisions=True,
            return_boundary_decisions=True,
            return_canonical_decisions=True,
        )

    # Carry each traversed location page's own MediaWiki categories onto its candidate row so the
    # draft can type the card from the authoritative wiki signal (e.g. Andorhal -> "Destroyed
    # settlements" -> ruins; Hearthglen -> "Towns" -> town) instead of fragile evidence-text words.
    for snapshot in source_snapshots:
        if str(snapshot.get("auxiliary_role", "")).strip() != "location_profile":
            continue
        location_id = str(snapshot.get("auxiliary_target_id", "")).strip()
        categories = snapshot.get("categories") or []
        if location_id and categories and location_id in location_candidate_map:
            location_candidate_map[location_id]["categories"] = list(categories)

    def _write(
        path: Path,
        *,
        instance_summary_map: dict[str, str] | None = None,
    ) -> tuple[Path | None, dict[str, object] | None]:
        fact_pack = fact_packs_by_entity.get(path.stem)
        if fact_pack is None:
            fact_pack = json.loads(path.read_text(encoding="utf-8"))
        entity_type = str(fact_pack.get("entity_type", ""))
        entity_id = str(fact_pack.get("entity_id", path.stem))
        if entity_type in {"zone", "instance"} and evidence_rows:
            finalize_trace.begin(entity_id)
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
                    questline_card_metadata={
                        cluster_id: row
                        for cluster_id, row in card_metadata_by_cluster.items()
                        if str(row.get("zone_id", "")).strip() == entity_id
                    },
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
                    quest_descriptions_by_node=quest_descriptions_by_node,
                    instance_summary_map=instance_summary_map,
                )
            else:
                lore_source = next(
                    (
                        row
                        for row in instance_lore_rows
                        if str(row.get("instance_id", "")).strip() == entity_id
                    ),
                    None,
                )
                parent_zone_id = str(fact_pack.get("parent_zone_id", "")).strip()
                parent_zone_evidence = (
                    [
                        row
                        for row in evidence_rows
                        if str(row.get("subject_id", "")).strip() == parent_zone_id
                    ]
                    if parent_zone_id
                    else []
                )
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
                                instance_section_blocks = [
                                    row for row in blocks if isinstance(row, dict)
                                ]
                            break
                selection_sink: list[InstanceKeyCharacterSelection] = []
                draft = build_instance_page(
                    enriched_fact_pack,
                    scoped_evidence,
                    lore_source,
                    parent_zone_evidence_rows=parent_zone_evidence,
                    faction_profile_targets=faction_profile_targets,
                    section_blocks=instance_section_blocks,
                    snapshots=source_snapshots,
                    selection_sink=selection_sink,
                )
                # Reuse the exact selection the page emitted from. Guarantees the sidecar
                # merge ranks match the page cast (no second, divergent LLM pass).
                if selection_sink:
                    instance_key_character_decisions = _build_key_character_decision_row(
                        instance_id=entity_id,
                        instance_name=str(enriched_fact_pack.get("name", entity_id)),
                        selection=selection_sink[0],
                        emitted_cards=draft.get("key_characters", []),
                    )
            prose_finalize_records = finalize_trace.drain()
            entity_dir = stage_dir / f"{entity_type}_page"
            entity_dir.mkdir(parents=True, exist_ok=True)
            out_path = entity_dir / f"{entity_id}.json"
            overflow = draft.pop("draft_overflow_decisions", None)
            draft = normalize_display_payload(draft)
            write_json(out_path, draft)
            decision: dict[str, object] = {
                "entity_id": entity_id,
                "entity_type": f"{entity_type}_page",
                "generation_mode": "deterministic_evidence_pack",
                "schema_repair_applied": "no",
                "prompt_profile": "wiki_first_v1",
            }
            if isinstance(overflow, list):
                decision["questline_overflow"] = overflow
            if prose_finalize_records:
                decision["prose_finalize"] = prose_finalize_records
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
        llm_draft: dict[str, Any] | None = None
        used_schema_retry = False
        for attempt in range(1, attempts + 1):
            llm_draft, mode = generate_entity_draft(
                fact_pack,
                entity_type,
                context=context,
                trace=trace,
            )
            if is_valid_draft(entity_type, llm_draft):
                break
            used_schema_retry = True
            if attempt == attempts:
                raise RuntimeError(
                    f"draft for entity '{entity_id}' is invalid after "
                    f"{attempts} schema-guarded attempts"
                )
        if llm_draft is None:  # pragma: no cover
            raise RuntimeError(f"draft generation returned no payload for '{entity_id}'")
        entity_dir = stage_dir / entity_type
        entity_dir.mkdir(parents=True, exist_ok=True)
        out_path = entity_dir / f"{llm_draft['id']}.json"
        llm_draft = normalize_display_payload(llm_draft)
        write_json(out_path, llm_draft)
        decision = {
            "entity_id": str(llm_draft["id"]),
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
    prose_finalize_decisions: list[dict[str, Any]] = []
    instance_summary_map: dict[str, str] = {}

    def _record_result(output_path: Path | None, decision: dict[str, object] | None) -> None:
        if output_path is not None:
            outputs.append(output_path)
        if decision is not None:
            kc_decision = decision.pop("instance_key_character_decisions", None)
            if isinstance(kc_decision, dict):
                instance_key_character_decisions.append(kc_decision)
            prose_records = decision.pop("prose_finalize", None)
            if isinstance(prose_records, list):
                prose_finalize_decisions.extend(prose_records)
            overflow = decision.pop("questline_overflow", None)
            decisions.append(decision)
            if isinstance(overflow, list):
                for row in overflow:
                    if isinstance(row, dict):
                        decisions.append(
                            {
                                "entity_id": str(
                                    row.get("entity_id", decision.get("entity_id", ""))
                                ),
                                "entity_type": str(row.get("entity_type", "questline_cluster")),
                                "generation_mode": "deterministic_evidence_pack",
                                "reason": str(row.get("reason", "questline_overflow")),
                                "cluster_id": str(row.get("cluster_id", "")),
                            }
                        )

    def _run_paths(
        paths: list[Path],
        *,
        summary_map: dict[str, str] | None = None,
    ) -> list[Path]:
        written: list[Path] = []
        if not paths:
            return written
        with ThreadPoolExecutor(max_workers=max_entity_concurrency) as executor:
            futures = [
                executor.submit(_write, path, instance_summary_map=summary_map) for path in paths
            ]
            for future in futures:
                output_path, decision = future.result()
                if output_path is not None:
                    written.append(output_path)
                _record_result(output_path, decision)
        return written

    def _entity_type_for_path(path: Path) -> str:
        fact_pack = fact_packs_by_entity.get(path.stem)
        if not fact_pack:
            fact_pack = json.loads(path.read_text(encoding="utf-8"))
        return str(fact_pack.get("entity_type", ""))

    instance_paths = [path for path in fact_pack_paths if _entity_type_for_path(path) == "instance"]
    zone_paths = [path for path in fact_pack_paths if _entity_type_for_path(path) == "zone"]
    other_paths = [
        path for path in fact_pack_paths if _entity_type_for_path(path) not in {"instance", "zone"}
    ]

    for output_path in _run_paths(instance_paths):
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            instance_id = str(payload.get("instance_id", "")).strip()
            at_a_glance = str(payload.get("at_a_glance", "")).strip()
            if instance_id and at_a_glance:
                instance_summary_map[instance_id] = at_a_glance
    _run_paths(zone_paths, summary_map=instance_summary_map)
    _run_paths(other_paths)
    write_json((stage_dir / "draft_decisions.json"), decisions)
    decisions_dir = context.data_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    write_json((decisions_dir / "temporal_evidence_decisions.json"), temporal_decisions)
    write_json(
        (decisions_dir / "entry_state_contract_decisions.json"),
        entry_state_contract_decisions,
    )
    write_json((decisions_dir / "content_boundary_decisions.json"), content_boundary_decisions)
    write_json(
        (decisions_dir / "canonical_temporal_evidence_decisions.json"),
        canonical_temporal_decisions,
    )
    write_json(
        (decisions_dir / "instance_key_character_decisions.json"), instance_key_character_decisions
    )
    write_json((decisions_dir / "prose_finalize_decisions.json"), prose_finalize_decisions)
    return outputs
