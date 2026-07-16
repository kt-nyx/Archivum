"""Shared validation context builders for pipeline validate and semantics --strict."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.common.run_context import RunContext
from pipeline.contracts.models import (
    InstanceKeyCharacterDecisionArtifact,
    LocationSelectionArtifact,
    QuestlineCardMetadataArtifact,
)
from pipeline.discovery.questline_significance import selected_candidate_ids_by_zone
from pipeline.generate.draft.card_evidence_pack import load_card_evidence_pack_artifact
from pipeline.generate.draft.model_versions import PROSE_FINALIZE_DECISION_SCHEMA
from pipeline.ingest.snapshots import load_source_snapshots


@dataclass
class ValidationRunResources:
    source_snapshots: list[dict[str, Any]] = field(default_factory=list)
    questline_decisions: list[dict[str, Any]] = field(default_factory=list)
    questline_cluster_rankings: list[dict[str, Any]] = field(default_factory=list)
    questline_card_metadata: list[dict[str, Any]] = field(default_factory=list)
    entry_state_contracts: list[dict[str, Any]] = field(default_factory=list)
    location_decisions: list[dict[str, Any]] = field(default_factory=list)
    location_coverage: list[dict[str, Any]] = field(default_factory=list)
    # Slice 8 release-gate sidecars: per-card evidence packs, instance participant admissions, and
    # the questline CTA finalize records whose final lint outcome the strict gate re-checks.
    card_evidence_packs: list[dict[str, Any]] = field(default_factory=list)
    instance_participant_decisions: list[dict[str, Any]] = field(default_factory=list)
    cta_finalize_records: list[dict[str, Any]] = field(default_factory=list)
    fact_check_target_entity_ids: list[str] = field(default_factory=list)
    fact_check_target_reasons: dict[str, list[str]] = field(default_factory=dict)
    linker_manual_review_by_entity: dict[str, int] = field(default_factory=dict)
    # Per-page faction-candidate names from the draft's ``major_factions.candidates`` finalize
    # decision — the match source for structure.uncarded_current_actor until Slice 13 re-points
    # it at the Slice 12 organization registry.
    faction_candidate_names_by_entity: dict[str, list[str]] = field(default_factory=dict)


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
    resources.source_snapshots = load_source_snapshots(snapshots_path, missing_ok=True)

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

    prose_finalize_path = run_root / "data" / "decisions" / "prose_finalize_decisions.json"
    if prose_finalize_path.exists():
        blob = json.loads(prose_finalize_path.read_text(encoding="utf-8"))
        expected_schema = PROSE_FINALIZE_DECISION_SCHEMA
        if not isinstance(blob, dict):
            raise ValueError(
                "prose_finalize_decisions artifact from draft_writer must be an object with "
                f"schema_version {expected_schema}"
            )
        if blob.get("schema_version") != expected_schema or blob.get("producer") != "draft_writer":
            raise ValueError(
                "prose_finalize_decisions artifact from draft_writer has incompatible schema; "
                f"expected {expected_schema}"
            )
        records = blob.get("decisions")
        if not isinstance(records, list):
            raise ValueError(
                "prose_finalize_decisions artifact from draft_writer has non-list decisions"
            )
        for row in records:
            if not isinstance(row, dict):
                continue
            stage = str(row.get("stage", ""))
            entity_id = row.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            if stage == "questline_cta.finalize":
                # Slice 8 release gate re-checks the *persisted* final CTA lint outcome: a finalize
                # record whose ``final_lint_issues`` is non-empty is a malformed final clause that
                # slipped past the synthesis-time gate.
                resources.cta_finalize_records.append(row)
                continue
            if stage != "major_factions.candidates":
                continue
            names = resources.faction_candidate_names_by_entity.setdefault(entity_id, [])
            candidates = row.get("candidates")
            for candidate in candidates if isinstance(candidates, list) else []:
                if not isinstance(candidate, dict):
                    continue
                name = str(candidate.get("name", "")).strip()
                if name and name not in names:
                    names.append(name)

    questline_decisions_path = (
        run_root / "data" / "decisions" / "questline_inclusion_decisions.json"
    )
    if questline_decisions_path.exists():
        blob = json.loads(questline_decisions_path.read_text(encoding="utf-8"))
        if isinstance(blob, list):
            resources.questline_decisions = [row for row in blob if isinstance(row, dict)]

    location_decisions_path = run_root / "data" / "decisions" / "location_selection_decisions.json"
    if location_decisions_path.exists():
        artifact = LocationSelectionArtifact.model_validate(
            json.loads(location_decisions_path.read_text(encoding="utf-8"))
        )
        resources.location_decisions = [row.model_dump(mode="json") for row in artifact.decisions]
        resources.location_coverage = [row.model_dump(mode="json") for row in artifact.coverage]

    arc_selection_path = run_root / "data" / "discovery" / "questline_arc_selection.json"
    if arc_selection_path.exists():
        resources.questline_cluster_rankings = [
            {"zone_id": zone_id, "included_cluster_ids": candidate_ids}
            for zone_id, candidate_ids in selected_candidate_ids_by_zone(arc_selection_path).items()
        ]

    metadata_path = run_root / "data" / "discovery" / "zone_questline_card_metadata.json"
    if metadata_path.exists():
        metadata_artifact = QuestlineCardMetadataArtifact.model_validate(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )
        resources.questline_card_metadata = [
            row.model_dump(mode="json") for row in metadata_artifact.metadata
        ]

    entry_state_path = run_root / "data" / "decisions" / "entry_state_contract_decisions.json"
    if entry_state_path.exists():
        blob = json.loads(entry_state_path.read_text(encoding="utf-8"))
        if (
            not isinstance(blob, dict)
            or blob.get("schema_version") != "entry_state_contract_decision.v1"
            or blob.get("producer") != "draft_writer"
            or not isinstance(blob.get("decisions"), list)
        ):
            raise ValueError(
                "entry_state_contract_decisions reader: expected artifact from draft_writer "
                "with schema entry_state_contract_decision.v1"
            )
        resources.entry_state_contracts = [
            row for row in blob["decisions"] if isinstance(row, dict)
        ]

    card_pack_path = run_root / "data" / "decisions" / "card_evidence_pack_decisions.json"
    if card_pack_path.exists():
        pack_artifact = load_card_evidence_pack_artifact(
            json.loads(card_pack_path.read_text(encoding="utf-8"))
        )
        resources.card_evidence_packs = [
            row.model_dump(mode="json") for row in pack_artifact.decisions
        ]

    kc_path = run_root / "data" / "decisions" / "instance_key_character_decisions.json"
    if kc_path.exists():
        kc_artifact = InstanceKeyCharacterDecisionArtifact.model_validate(
            json.loads(kc_path.read_text(encoding="utf-8"))
        )
        resources.instance_participant_decisions = [
            row.model_dump(mode="json") for row in kc_artifact.decisions
        ]

    return resources


def load_validation_run_resources_from_context(context: RunContext) -> ValidationRunResources:
    return load_validation_run_resources(context.root_dir)


def wiki_first_entity_flags(
    entity_id: str,
    *,
    questline_decisions: list[dict[str, Any]],
    questline_cluster_rankings: list[dict[str, Any]] | None = None,
    questline_card_metadata: list[dict[str, Any]] | None = None,
    entry_state_contracts: list[dict[str, Any]] | None = None,
    location_decisions: list[dict[str, Any]] | None = None,
    location_coverage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    questline_cluster_rankings = questline_cluster_rankings or []
    questline_card_metadata = questline_card_metadata or []
    entry_state_contracts = entry_state_contracts or []
    location_decisions = location_decisions or []
    location_coverage = location_coverage or []
    questline_row = next(
        (row for row in questline_decisions if str(row.get("subject_id", "")) == entity_id),
        None,
    )
    location_include_count = sum(
        1
        for row in location_decisions
        if str(row.get("zone_id", "")).strip() == entity_id
        and str(row.get("state", "")) == "selected"
    )
    location_coverage_status = next(
        (
            str(row.get("status", ""))
            for row in location_coverage
            if str(row.get("zone_id", "")).strip() == entity_id
        ),
        "",
    )
    rankings_by_zone = {
        str(row.get("zone_id", "")): [str(value) for value in row.get("included_cluster_ids", [])]
        for row in questline_cluster_rankings
        if isinstance(row, dict)
    }
    questline_included_cluster_ids = rankings_by_zone.get(entity_id, [])
    questline_card_metadata_by_cluster = {
        str(row.get("cluster_id", "")).strip(): row
        for row in questline_card_metadata
        if str(row.get("zone_id", "")).strip() == entity_id
        and str(row.get("cluster_id", "")).strip()
    }
    entry_state_contract = next(
        (
            row
            for row in entry_state_contracts
            if str(row.get("entity_id", "")).strip() == entity_id
        ),
        {},
    )
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
        "location_coverage_status": location_coverage_status,
        "questline_included_cluster_ids": questline_included_cluster_ids,
        "questline_card_metadata_by_cluster": questline_card_metadata_by_cluster,
        "questline_excluded_cluster_ids": questline_excluded_cluster_ids,
        "entry_state_active_expansion": (
            entry_state_contract.get("active_expansion")
            if isinstance(entry_state_contract, dict)
            else None
        ),
    }


def release_gate_entity_flags(
    entity_id: str,
    *,
    resources: ValidationRunResources,
) -> dict[str, Any]:
    """Per-entity release-gate context: card evidence packs, participant admissions, questline
    setup coverage, and the final-CTA lint outcome (Slice 8 strict release gate).

    The gate rules consult these only when ``release_gate`` is set. Each map is keyed by the same
    id the rendered card carries (``card_id``/``location_id``/``candidate_id``), so the strict gate
    can confirm every rendered card agrees with the selection/evidence sidecar it was drawn from.
    """
    packs_by_card_id = {
        str(row.get("card_id", "")).strip(): row
        for row in resources.card_evidence_packs
        if str(row.get("card_id", "")).strip()
    }
    location_selection_by_id = {
        str(row.get("location_id", "")).strip(): row
        for row in resources.location_decisions
        if str(row.get("location_id", "")).strip()
    }
    instance_participants_by_candidate_id: dict[str, dict[str, Any]] = {}
    instance_decision_present = False
    for row in resources.instance_participant_decisions:
        if str(row.get("instance_id", "")).strip() != entity_id:
            continue
        instance_decision_present = True
        for candidate in row.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id", "")).strip()
            if candidate_id:
                instance_participants_by_candidate_id[candidate_id] = candidate

    entry_state_contract = next(
        (
            row
            for row in resources.entry_state_contracts
            if str(row.get("entity_id", "")).strip() == entity_id
        ),
        None,
    )
    questline_setup_clusters: set[str] = set()
    if isinstance(entry_state_contract, dict):
        for anchor in entry_state_contract.get("source_anchor_refs", []) or []:
            if not isinstance(anchor, dict):
                continue
            if str(anchor.get("kind", "")) != "questline_setup":
                continue
            if anchor.get("setup_snippets"):
                cluster_id = str(anchor.get("cluster_id", "")).strip()
                if cluster_id:
                    questline_setup_clusters.add(cluster_id)

    cta_lint_failed = any(
        str(row.get("entity_id", "")).strip() == entity_id and (row.get("final_lint_issues") or [])
        for row in resources.cta_finalize_records
    )
    return {
        "release_card_evidence_packs": packs_by_card_id,
        "release_card_packs_present": bool(packs_by_card_id),
        "release_location_selection_by_id": location_selection_by_id,
        "release_instance_participants": instance_participants_by_candidate_id,
        "release_instance_decision_present": instance_decision_present,
        "release_questline_setup_clusters": questline_setup_clusters,
        "release_entry_state_present": entry_state_contract is not None,
        "release_cta_lint_failed": cta_lint_failed,
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
        "faction_candidate_names": resources.faction_candidate_names_by_entity.get(entity_id, []),
        "similarity_require_snapshots": normalized_profile in {"warn", "strict"},
        **wiki_first_entity_flags(
            entity_id,
            questline_decisions=resources.questline_decisions,
            questline_cluster_rankings=resources.questline_cluster_rankings,
            questline_card_metadata=resources.questline_card_metadata,
            entry_state_contracts=resources.entry_state_contracts,
            location_decisions=resources.location_decisions,
            location_coverage=resources.location_coverage,
        ),
        **release_gate_entity_flags(entity_id, resources=resources),
    }
