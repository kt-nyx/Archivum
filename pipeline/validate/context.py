"""Shared validation context builders for pipeline validate and semantics --strict."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.discovery.pilot_questline_registry import structural_expectations_for_zone
from pipeline.discovery.questline_significance import load_included_cluster_ids_by_zone


@dataclass
class ValidationRunResources:
    source_snapshots: list[dict[str, Any]] = field(default_factory=list)
    questline_decisions: list[dict[str, Any]] = field(default_factory=list)
    questline_cluster_rankings: list[dict[str, Any]] = field(default_factory=list)
    questline_card_metadata: list[dict[str, Any]] = field(default_factory=list)
    location_decisions: list[dict[str, Any]] = field(default_factory=list)
    fact_check_target_entity_ids: list[str] = field(default_factory=list)
    fact_check_target_reasons: dict[str, list[str]] = field(default_factory=dict)
    linker_manual_review_by_entity: dict[str, int] = field(default_factory=dict)


def resolve_draft_entity_id(draft_path: Path, payload: dict[str, Any]) -> str:
    for key in ("id", "zone_id", "instance_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    stem = draft_path.stem.strip()
    return stem or "unknown-entity"


def load_validation_run_resources(run_root: Path) -> ValidationRunResources:
    """Load ingest snapshots, decisions, and fact-check targets from a run root."""
    resources = ValidationRunResources()
    snapshots_path = run_root / "data" / "ingest" / "source_snapshots.json"
    if snapshots_path.exists():
        blob = json.loads(snapshots_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            resources.source_snapshots = [row for row in blob if isinstance(row, dict)]

    linker_report_path = run_root / "data" / "linker" / "linker_qa_report.json"
    if linker_report_path.exists():
        linker_payload = json.loads(linker_report_path.read_text(encoding="utf-8"))
        manual_rows = linker_payload.get("manual_review_candidates", [])
        if isinstance(manual_rows, list):
            for row in manual_rows:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get("entity_id")
                if isinstance(entity_id, str):
                    resources.linker_manual_review_by_entity[entity_id] = (
                        resources.linker_manual_review_by_entity.get(entity_id, 0) + 1
                    )

    fact_check_target_reasons: dict[str, set[str]] = {}
    for entity_id in resources.linker_manual_review_by_entity:
        fact_check_target_reasons.setdefault(entity_id, set()).add("linker_manual_review")

    coalesce_decisions_path = run_root / "data" / "coalesced" / "coalesce_decisions.json"
    if coalesce_decisions_path.exists():
        coalesce_blob = json.loads(coalesce_decisions_path.read_text(encoding="utf-8"))
        if isinstance(coalesce_blob, list):
            for row in coalesce_blob:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get("entity_id")
                if not isinstance(entity_id, str) or not entity_id:
                    continue
                tie_break_events = row.get("tie_break_events")
                if isinstance(tie_break_events, int) and tie_break_events > 0:
                    fact_check_target_reasons.setdefault(entity_id, set()).add("coalesce_tie_break")
                confidence = row.get("confidence")
                if isinstance(confidence, (int, float)) and float(confidence) < 0.88:
                    fact_check_target_reasons.setdefault(entity_id, set()).add(
                        "coalesce_low_confidence"
                    )

    draft_decisions_path = run_root / "data" / "drafts" / "draft_decisions.json"
    if draft_decisions_path.exists():
        draft_blob = json.loads(draft_decisions_path.read_text(encoding="utf-8"))
        if isinstance(draft_blob, list):
            for row in draft_blob:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get("entity_id")
                if not isinstance(entity_id, str) or not entity_id:
                    continue
                if str(row.get("schema_repair_applied", "")).lower() == "yes":
                    fact_check_target_reasons.setdefault(entity_id, set()).add(
                        "draft_schema_repair"
                    )

    resources.fact_check_target_entity_ids = sorted(fact_check_target_reasons)
    resources.fact_check_target_reasons = {
        entity_id: sorted(reasons) for entity_id, reasons in fact_check_target_reasons.items()
    }

    questline_decisions_path = (
        run_root / "data" / "decisions" / "questline_inclusion_decisions.json"
    )
    if questline_decisions_path.exists():
        blob = json.loads(questline_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            resources.questline_decisions = [row for row in blob if isinstance(row, dict)]

    location_decisions_path = (
        run_root / "data" / "decisions" / "location_significance_decisions.json"
    )
    if location_decisions_path.exists():
        blob = json.loads(location_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            resources.location_decisions = [row for row in blob if isinstance(row, dict)]

    rankings_path = run_root / "data" / "discovery" / "zone_quest_cluster_rankings.json"
    if rankings_path.exists():
        blob = json.loads(rankings_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            resources.questline_cluster_rankings = [row for row in blob if isinstance(row, dict)]

    metadata_path = run_root / "data" / "discovery" / "zone_questline_card_metadata.json"
    if metadata_path.exists():
        blob = json.loads(metadata_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            resources.questline_card_metadata = [row for row in blob if isinstance(row, dict)]

    return resources


def load_validation_run_resources_from_context(context: RunContext) -> ValidationRunResources:
    return load_validation_run_resources(context.root_dir)


def wiki_first_entity_flags(
    entity_id: str,
    *,
    questline_decisions: list[dict[str, Any]],
    questline_cluster_rankings: list[dict[str, Any]] | None = None,
    questline_card_metadata: list[dict[str, Any]] | None = None,
    location_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    questline_cluster_rankings = questline_cluster_rankings or []
    questline_card_metadata = questline_card_metadata or []
    location_decisions = location_decisions or []
    questline_row = next(
        (row for row in questline_decisions if str(row.get("subject_id", "")) == entity_id),
        None,
    )
    location_include_count = sum(
        1 for row in location_decisions if str(row.get("final_decision", "")) == "include"
    )
    rankings_by_zone = load_included_cluster_ids_by_zone(questline_cluster_rankings)
    questline_included_cluster_ids = rankings_by_zone.get(entity_id, [])
    questline_card_metadata_by_cluster = {
        str(row.get("cluster_id", "")).strip(): row
        for row in questline_card_metadata
        if str(row.get("zone_id", "")).strip() == entity_id
        and str(row.get("cluster_id", "")).strip()
    }
    questline_excluded_cluster_ids = [
        str(row.get("subject_id", "")).strip()
        for row in questline_decisions
        if str(row.get("subject_type", "")) == "questline_cluster"
        and str(row.get("final_decision", "")).strip() == "exclude"
        and str((row.get("features") or {}).get("zone_id", row.get("zone_id", ""))).strip()
        in {"", entity_id}
    ]
    return {
        "questline_expect_include": str((questline_row or {}).get("final_decision", ""))
        == "include",
        "location_expect_card_count": location_include_count,
        "questline_included_cluster_ids": questline_included_cluster_ids,
        "questline_card_metadata_by_cluster": questline_card_metadata_by_cluster,
        "questline_excluded_cluster_ids": questline_excluded_cluster_ids,
        "pilot_questline_expectations": structural_expectations_for_zone(entity_id),
    }


def build_entity_validation_context(
    *,
    entity_id: str,
    fact_check_profile: str,
    release_gate: bool,
    resources: ValidationRunResources,
    fact_check_web_search: bool = False,
    fact_check_max_web_results: int = 3,
    fact_check_enable_llm: bool = False,
    fact_check_llm_model: str = "gpt-5.5",
) -> dict[str, Any]:
    normalized_profile = fact_check_profile.strip().lower()
    return {
        "fact_check_profile": normalized_profile,
        "release_gate": release_gate,
        "fact_check_web_search": fact_check_web_search,
        "fact_check_max_web_results": fact_check_max_web_results,
        "fact_check_enable_llm": fact_check_enable_llm,
        "fact_check_llm_model": fact_check_llm_model,
        "fact_check_source_snapshots": resources.source_snapshots,
        "fact_check_target_entity_ids": resources.fact_check_target_entity_ids,
        "fact_check_target_reasons": resources.fact_check_target_reasons,
        "similarity_require_snapshots": normalized_profile in {"warn", "strict"},
        **wiki_first_entity_flags(
            entity_id,
            questline_decisions=resources.questline_decisions,
            questline_cluster_rankings=resources.questline_cluster_rankings,
            questline_card_metadata=resources.questline_card_metadata,
            location_decisions=resources.location_decisions,
        ),
    }
