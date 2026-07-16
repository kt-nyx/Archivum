"""Machine-readable run quality summary (Slice 9, item 2).

This aggregates the decision/evidence sidecars and validation report a completed run already
emits into one compact, machine-readable object. It introduces no new selection or classification
logic: every field is read from an existing versioned artifact, and a missing artifact degrades to
an empty/None section rather than fabricating a value. The summary is the repeatable review surface
the pilot matrix (item 4) and the editorial-review rubric consume.

The reader is deliberately zone-neutral: it keys everything off ids the artifacts already carry and
records the schema versions it observed, so a quality comparison can surface a schema, source, or
model change before attributing a difference to code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline.contracts.models import QuestlineArcSelectionArtifact
from pipeline.validate.context import ValidationRunResources, load_validation_run_resources

QUALITY_SUMMARY_SCHEMA = "run_quality_summary.v1"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_of_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _zone_and_instance_drafts(run_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    draft_root = run_root / "data" / "drafts"
    zones: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []
    for dir_name, bucket in (("zone_page", zones), ("instance_page", instances)):
        draft_dir = draft_root / dir_name
        if not draft_dir.exists():
            continue
        for draft_path in sorted(draft_dir.glob("*.json")):
            draft = _load_json(draft_path)
            if isinstance(draft, dict):
                bucket.append(draft)
    return zones, instances


def _selected_card_kinds(
    resources: ValidationRunResources,
) -> dict[str, Any]:
    """Kind admission of selected cards, straight from the selection/evidence sidecars."""
    by_card_type: dict[str, int] = {}
    for pack in resources.card_evidence_packs:
        card_type = str(pack.get("card_type", "")).strip() or "unknown"
        by_card_type[card_type] = by_card_type.get(card_type, 0) + 1

    location_entity_kinds: dict[str, int] = {}
    for row in resources.location_decisions:
        if str(row.get("state", "")).strip() != "selected":
            continue
        kind = str(row.get("entity_kind", "")).strip() or "unknown"
        location_entity_kinds[kind] = location_entity_kinds.get(kind, 0) + 1

    key_character_entity_kinds: dict[str, int] = {}
    for decision in resources.instance_participant_decisions:
        for candidate in decision.get("candidates", []) or []:
            if not isinstance(candidate, dict) or not candidate.get("emitted"):
                continue
            kind = str(candidate.get("entity_kind", "")).strip() or "unknown"
            key_character_entity_kinds[kind] = key_character_entity_kinds.get(kind, 0) + 1

    return {
        "by_card_type": by_card_type,
        "location_entity_kinds": location_entity_kinds,
        "key_character_entity_kinds": key_character_entity_kinds,
    }


def _direct_evidence_coverage(resources: ValidationRunResources) -> dict[str, Any]:
    packs = resources.card_evidence_packs
    total = len(packs)
    with_identity = 0
    insufficient = 0
    by_card_type: dict[str, dict[str, int]] = {}
    for pack in packs:
        card_type = str(pack.get("card_type", "")).strip() or "unknown"
        bucket = by_card_type.setdefault(card_type, {"total": 0, "with_direct_identity": 0})
        bucket["total"] += 1
        has_identity = any(
            str(ref.get("role", "")) == "identity"
            for ref in pack.get("identity_evidence", []) or []
            if isinstance(ref, dict)
        )
        if has_identity:
            with_identity += 1
            bucket["with_direct_identity"] += 1
        if str(pack.get("sufficiency", "")).strip() != "ok":
            insufficient += 1
    return {
        "packs_total": total,
        "with_direct_identity": with_identity,
        "insufficient": insufficient,
        "coverage_ratio": (with_identity / total) if total else None,
        "by_card_type": by_card_type,
    }


def _deferred_retrieval_reasons(resources: ValidationRunResources) -> dict[str, Any]:
    deferred: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in resources.location_decisions:
        state = str(row.get("state", "")).strip()
        entry = {
            "location_id": str(row.get("location_id", "")).strip(),
            "zone_id": str(row.get("zone_id", "")).strip(),
            "reason_codes": [str(code) for code in row.get("reason_codes", []) or []],
        }
        if state == "deferred":
            deferred.append(entry)
        elif state == "rejected":
            rejected.append(entry)
    coverage = [
        {
            "zone_id": str(row.get("zone_id", "")).strip(),
            "status": str(row.get("status", "")).strip(),
            "selected_count": row.get("selected_count"),
            "desired_card_count": row.get("desired_card_count"),
            "reason_codes": [str(code) for code in row.get("reason_codes", []) or []],
        }
        for row in resources.location_coverage
    ]
    return {"location": {"deferred": deferred, "rejected": rejected, "coverage": coverage}}


def _questline_setup_coverage(resources: ValidationRunResources) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    for contract in resources.entry_state_contracts:
        setup_clusters: set[str] = set()
        setup_with_snippets = 0
        for anchor in contract.get("source_anchor_refs", []) or []:
            if not isinstance(anchor, dict):
                continue
            if str(anchor.get("kind", "")) != "questline_setup":
                continue
            cluster_id = str(anchor.get("cluster_id", "")).strip()
            if cluster_id:
                setup_clusters.add(cluster_id)
            if anchor.get("setup_snippets"):
                setup_with_snippets += 1
        active_expansion = contract.get("active_expansion")
        active_status = "unknown"
        if isinstance(active_expansion, dict):
            active_status = str(active_expansion.get("status", active_expansion.get("value", "")))
        elif isinstance(active_expansion, str) and active_expansion:
            active_status = active_expansion
        entities.append(
            {
                "entity_id": str(contract.get("entity_id", "")).strip(),
                "setup_cluster_count": len(setup_clusters),
                "setup_anchors_with_snippets": setup_with_snippets,
                "active_expansion_status": active_status,
            }
        )
    return {"entities": entities}


def _arc_family_variant_coverage(run_root: Path) -> dict[str, Any]:
    arc_path = run_root / "data" / "discovery" / "questline_arc_selection.json"
    blob = _load_json(arc_path)
    if blob is None:
        return {}
    artifact = QuestlineArcSelectionArtifact.model_validate(blob)
    selected_by_zone = {
        zone_id: list(candidate_ids)
        for zone_id, candidate_ids in artifact.selected_candidate_ids_by_zone.items()
    }
    selected_ids = {
        cid for ids in artifact.selected_candidate_ids_by_zone.values() for cid in ids
    }
    variant_selected = sum(
        1
        for candidate in artifact.candidates
        if candidate.candidate_id in selected_ids
        and (candidate.faction_variant or candidate.phase_variant)
    )
    return {
        "schema_version": artifact.schema_version,
        "families_total": len(artifact.families),
        "candidates_total": len(artifact.candidates),
        "variant_candidates_selected": variant_selected,
        "selected_by_zone": selected_by_zone,
        "coverage": [
            {
                "zone_id": row.zone_id,
                "status": row.status,
                "selected_candidate_ids": list(row.selected_candidate_ids),
                "reason_codes": list(row.reason_codes),
            }
            for row in artifact.coverage
        ],
        "exclusions": [
            {
                "zone_id": row.zone_id,
                "decision": row.decision,
                "candidate_ids": list(row.candidate_ids),
                "reason_codes": list(row.reason_codes),
            }
            for row in artifact.exclusions
        ],
    }


def _title_collisions(resources: ValidationRunResources) -> list[dict[str, Any]]:
    labels_by_zone: dict[str, dict[str, list[str]]] = {}
    for row in resources.questline_card_metadata:
        zone_id = str(row.get("zone_id", "")).strip()
        label = " ".join(
            part
            for part in (
                str(row.get("base_title", "")).strip(),
                str(row.get("faction_variant") or "").strip(),
                str(row.get("phase_variant") or "").strip(),
            )
            if part
        ).casefold()
        if not label:
            continue
        card_id = str(row.get("card_id", "")).strip()
        labels_by_zone.setdefault(zone_id, {}).setdefault(label, []).append(card_id)
    collisions: list[dict[str, Any]] = []
    for zone_id, by_label in labels_by_zone.items():
        for label, card_ids in by_label.items():
            if len(card_ids) > 1:
                collisions.append(
                    {"zone_id": zone_id, "normalized_label": label, "card_ids": sorted(card_ids)}
                )
    return collisions


def _final_cta_lint(resources: ValidationRunResources) -> dict[str, Any]:
    records = resources.cta_finalize_records
    failed = [
        {
            "entity_id": str(row.get("entity_id", "")).strip(),
            "final_lint_issues": [str(issue) for issue in row.get("final_lint_issues", []) or []],
        }
        for row in records
        if row.get("final_lint_issues")
    ]
    fallback_used = sum(1 for row in records if row.get("fallback_used"))
    return {
        "records_total": len(records),
        "failed": failed,
        "fallback_used": fallback_used,
    }


def _fact_check_summary(run_root: Path) -> dict[str, Any]:
    report = _load_json(run_root / "reports" / "validate" / "fact_check_report.json")
    if not isinstance(report, dict):
        return {}
    entities = []
    for row in report.get("entities", []) or []:
        if not isinstance(row, dict):
            continue
        review_queue = row.get("review_queue", []) or []
        entities.append(
            {
                "entity_id": str(row.get("entity_id", "")).strip(),
                "claim_count": row.get("claim_count", 0),
                "review_queue_count": len(review_queue) if isinstance(review_queue, list) else 0,
            }
        )
    return {
        "profile": report.get("profile"),
        "llm_enabled": report.get("llm_enabled"),
        "target_entity_count": report.get("target_entity_count"),
        "entities": entities,
    }


def _strict_release(run_root: Path) -> dict[str, Any]:
    report = _load_json(run_root / "reports" / "validate" / "validation_report.json")
    if not isinstance(report, dict):
        return {}
    return {
        "passed": report.get("passed"),
        "release_gate": report.get("release_gate"),
        "release_certified": report.get("release_certified"),
        "fact_check_profile": report.get("fact_check_profile"),
    }


def _schema_versions(run_root: Path) -> dict[str, Any]:
    """Observed schema versions of the cross-stage artifacts this plan versioned."""
    decisions = run_root / "data" / "decisions"
    discovery = run_root / "data" / "discovery"
    artifact_paths = {
        "location_selection": decisions / "location_selection_decisions.json",
        "card_evidence_pack": decisions / "card_evidence_pack_decisions.json",
        "instance_key_character_decision": decisions / "instance_key_character_decisions.json",
        "entry_state_contract_decision": decisions / "entry_state_contract_decisions.json",
        "prose_finalize_decision": decisions / "prose_finalize_decisions.json",
        "questline_card_metadata": discovery / "zone_questline_card_metadata.json",
        "questline_arc_selection": discovery / "questline_arc_selection.json",
    }
    versions: dict[str, Any] = {}
    for key, path in artifact_paths.items():
        blob = _load_json(path)
        versions[key] = (
            str(blob.get("schema_version")) if isinstance(blob, dict) else None
        )
    manifest = _load_json(decisions / "temporal_model_manifest.json")
    if isinstance(manifest, dict) and isinstance(manifest.get("versions"), dict):
        versions["temporal_model_manifest"] = manifest["versions"]
    return versions


def _source_input_hashes(run_root: Path, resources: ValidationRunResources) -> dict[str, Any]:
    manifest = _load_json(run_root / "source_manifest.json")
    manifest_identity: dict[str, Any] = {}
    if isinstance(manifest, list):
        for row in manifest:
            if not isinstance(row, dict):
                continue
            for key in ("manifest_run_id", "selection_version", "policy_version"):
                value = str(row.get(key, "")).strip()
                if value:
                    manifest_identity.setdefault(key, value)
    snapshot_revision_ids = sorted(
        {
            str(snapshot.get("revision_id", "")).strip()
            for snapshot in resources.source_snapshots
            if isinstance(snapshot, dict) and str(snapshot.get("revision_id", "")).strip()
        }
    )
    return {
        "source_manifest_sha256": _sha256_of_file(run_root / "source_manifest.json"),
        "manifest_identity": manifest_identity,
        "snapshot_count": len(resources.source_snapshots),
        "snapshot_revision_ids": snapshot_revision_ids,
    }


def _model_prompt_identifiers(run_root: Path) -> dict[str, Any]:
    report = _load_json(run_root / "reports" / "validate" / "validation_report.json")
    fact_check_model = None
    no_llm_fact_check = None
    if isinstance(report, dict):
        fact_check_model = report.get("llm_model")
        no_llm_fact_check = report.get("no_llm_fact_check")
    manifest = _load_json(run_root / "data" / "decisions" / "temporal_model_manifest.json")
    temporal_versions = (
        manifest.get("versions") if isinstance(manifest, dict) else None
    )
    return {
        "fact_check_llm_model": fact_check_model,
        "no_llm_fact_check": no_llm_fact_check,
        "temporal_versions": temporal_versions,
    }


def build_run_quality_summary(run_root: Path) -> dict[str, Any]:
    """Aggregate a completed run's versioned sidecars into one machine-readable summary."""
    resources = load_validation_run_resources(run_root)
    zones, instances = _zone_and_instance_drafts(run_root)
    run_id = ""
    report = _load_json(run_root / "reports" / "validate" / "validation_report.json")
    if isinstance(report, dict):
        run_id = str(report.get("run_id", "")).strip()
    if not run_id:
        run_id = run_root.name
    return {
        "schema_version": QUALITY_SUMMARY_SCHEMA,
        "run_id": run_id,
        "run_root": run_root.name,
        "page_counts": {"zone_pages": len(zones), "instance_pages": len(instances)},
        "selected_card_kinds": _selected_card_kinds(resources),
        "direct_evidence_coverage": _direct_evidence_coverage(resources),
        "deferred_retrieval_reasons": _deferred_retrieval_reasons(resources),
        "questline_setup_coverage": _questline_setup_coverage(resources),
        "arc_family_variant_coverage": _arc_family_variant_coverage(run_root),
        "title_collisions": _title_collisions(resources),
        "final_cta_lint": _final_cta_lint(resources),
        "fact_check": _fact_check_summary(run_root),
        "strict_release": _strict_release(run_root),
        "schema_versions": _schema_versions(run_root),
        "source_input_hashes": _source_input_hashes(run_root, resources),
        "model_prompt_identifiers": _model_prompt_identifiers(run_root),
    }


def write_run_quality_summary(run_root: Path, out: Path | None = None) -> Path:
    """Write the machine-readable quality summary JSON and return its path."""
    summary = build_run_quality_summary(run_root)
    out_path = out if out is not None else run_root / "reports" / "run_quality_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return out_path
