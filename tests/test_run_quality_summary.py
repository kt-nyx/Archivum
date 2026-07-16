"""Slice 9, item 2: machine-readable run quality summary.

Synthetic, invented-subject run artifacts prove the aggregator surfaces every required field
(selected-card kinds, direct-evidence coverage, deferred retrieval reasons, questline setup
coverage, arc-family/variant coverage, title collisions, final CTA lint, fact-check scope, strict
release outcome, schema versions, source/input hashes, model/prompt identifiers) without encoding
any pilot output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.validate.quality_summary import (
    QUALITY_SUMMARY_SCHEMA,
    build_run_quality_summary,
    write_run_quality_summary,
)

ZONE_ID = "zone-fake-vale"
INSTANCE_ID = "instance-archive-vault"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_full_run(run_root: Path) -> None:
    # Drafts (page counts only).
    _write(run_root / "data" / "drafts" / "zone_page" / f"{ZONE_ID}.json", {"zone_id": ZONE_ID})
    _write(
        run_root / "data" / "drafts" / "instance_page" / f"{INSTANCE_ID}.json",
        {"instance_id": INSTANCE_ID},
    )

    # Source manifest + snapshots (input hashes / identity).
    _write(
        run_root / "source_manifest.json",
        [
            {
                "entity_id": ZONE_ID,
                "entity_type": "zone",
                "source_id": "src-fake-1",
                "manifest_run_id": "manifest-fake-v1",
                "selection_version": "sel-v1",
                "policy_version": "policy-v1",
            }
        ],
    )
    _write(
        run_root / "data" / "ingest" / "source_snapshots.json",
        [
            {
                "entity_id": ZONE_ID,
                "entity_type": "zone",
                "source_id": "src-fake-1",
                "revision_id": "mw:101",
                "infobox": {},
                "section_blocks": [],
            }
        ],
    )

    # Location selection (selected kinds + deferred/rejected reasons + coverage).
    _write(
        run_root / "data" / "decisions" / "location_selection_decisions.json",
        {
            "schema_version": "location_selection.v1",
            "producer": "discovery",
            "decisions": [
                {
                    "schema_version": "location_selection_decision.v1",
                    "decision_id": "loc-decision-1",
                    "zone_id": ZONE_ID,
                    "location_id": "location-stillwater-rest",
                    "name": "Stillwater Rest",
                    "source_link": "/wiki/Stillwater_Rest",
                    "candidate_rank": 0,
                    "state": "selected",
                    "entity_kind": "place",
                    "reason_codes": ["include"],
                },
                {
                    "schema_version": "location_selection_decision.v1",
                    "decision_id": "loc-decision-2",
                    "zone_id": ZONE_ID,
                    "location_id": "location-north-road",
                    "name": "North Road",
                    "source_link": "/wiki/North_Road",
                    "candidate_rank": 1,
                    "state": "deferred",
                    "entity_kind": "place",
                    "reason_codes": ["budget_filled"],
                },
                {
                    "schema_version": "location_selection_decision.v1",
                    "decision_id": "loc-decision-3",
                    "zone_id": ZONE_ID,
                    "location_id": "location-sealed-order",
                    "name": "Sealed Order",
                    "source_link": "/wiki/Sealed_Order",
                    "candidate_rank": 2,
                    "state": "rejected",
                    "entity_kind": "organization",
                    "reason_codes": ["not_a_place"],
                },
            ],
            "coverage": [
                {
                    "zone_id": ZONE_ID,
                    "desired_card_count": 6,
                    "selected_count": 1,
                    "probe_cap": 12,
                    "profile_cap": 8,
                    "probes_attempted": 3,
                    "profiles_attempted": 1,
                    "status": "coverage_met",
                    "attempted_candidate_ids": [],
                    "reason_codes": ["coverage_met"],
                }
            ],
        },
    )

    # Card evidence packs (direct-evidence coverage + by-card-type).
    _write(
        run_root / "data" / "decisions" / "card_evidence_pack_decisions.json",
        {
            "schema_version": "card_evidence_pack.v1",
            "producer": "draft_writer",
            "decisions": [
                {
                    "card_id": "location-stillwater-rest",
                    "card_type": "location",
                    "subject_id": "location-stillwater-rest",
                    "sufficiency": "ok",
                    "identity_evidence": [
                        {"role": "identity", "evidence_id": "ev-1", "owner_subject_id": "location-stillwater-rest"}
                    ],
                },
                {
                    "card_id": "faction-sealed-gate",
                    "card_type": "faction",
                    "subject_id": "faction-sealed-gate",
                    "sufficiency": "insufficient_identity_evidence",
                    "reason": "no identity evidence",
                },
            ],
        },
    )

    # Instance key-character admissions (selected kinds for key characters).
    _write(
        run_root / "data" / "decisions" / "instance_key_character_decisions.json",
        {
            "schema_version": "instance_key_character_decision.v1",
            "producer": "draft_writer",
            "decisions": [
                {
                    "instance_id": INSTANCE_ID,
                    "candidates": [
                        {
                            "candidate_id": "character-archivist-maelor",
                            "name": "Archivist Maelor",
                            "canonical_path": "/wiki/Archivist_Maelor",
                            "entity_kind_decision_id": "ek-1",
                            "entity_kind": "named_actor",
                            "instance_presence_evidence": ["source:x:section:encounter"],
                            "retail_scope": "retail_confirmed",
                            "admission": "eligible",
                            "final_selection_reason": "selected",
                            "final_role": "enemy",
                            "emitted": True,
                        },
                        {
                            "candidate_id": "group-vault-sentries",
                            "name": "Vault Sentries",
                            "canonical_path": "/wiki/Vault_Sentries",
                            "entity_kind_decision_id": "ek-2",
                            "entity_kind": "group_or_species",
                            "retail_scope": "unknown",
                            "admission": "rejected",
                            "emitted": False,
                        },
                    ],
                }
            ],
        },
    )

    # Entry-state contracts (questline setup coverage + active expansion).
    _write(
        run_root / "data" / "decisions" / "entry_state_contract_decisions.json",
        {
            "schema_version": "entry_state_contract_decision.v1",
            "producer": "draft_writer",
            "decisions": [
                {
                    "entity_id": ZONE_ID,
                    "source_anchor_refs": [
                        {
                            "kind": "questline_setup",
                            "cluster_id": "cluster-sealed-gate",
                            "setup_snippets": ["A vigil begins at the sealed gate."],
                        }
                    ],
                    "active_expansion": {"status": "resolved", "value": "wrath"},
                }
            ],
        },
    )

    # Questline card metadata (title collisions).
    _write(
        run_root / "data" / "discovery" / "zone_questline_card_metadata.json",
        {
            "schema_version": "questline_card_metadata.v2",
            "producer": "discovery.questline_card_polish",
            "metadata": [
                {
                    "schema_version": "questline_card_metadata.v2",
                    "metadata_id": "metadata-sealed-gate-1",
                    "zone_id": ZONE_ID,
                    "cluster_id": "cluster-sealed-gate",
                    "source_arc_id": "arc-sealed-gate",
                    "card_id": "cluster-sealed-gate",
                    "canonical_id": "cluster-sealed-gate",
                    "base_title": "The Sealed Gate",
                    "faction": "alliance",
                    "start_anchor": "A Vigil Begins",
                    "start_anchor_ref": "quest-vigil",
                    "chain_refs": ["quest-vigil", "quest-seal"],
                    "algorithm_version": "arc-v1",
                }
            ],
        },
    )

    # Arc selection (families / variants / coverage).
    _write(
        run_root / "data" / "discovery" / "questline_arc_selection.json",
        {
            "schema_version": "questline_arc_selection.v1",
            "producer": "discovery.questline_significance",
            "candidates": [
                {
                    "candidate_id": "arc-sealed-gate-alliance",
                    "zone_id": ZONE_ID,
                    "component_ids": ["comp-1"],
                    "quest_node_ids": ["quest-vigil"],
                    "base_title": "The Sealed Gate",
                    "faction_variant": "alliance",
                    "coherent_score": 4.0,
                }
            ],
            "families": [
                {
                    "family_id": "family-sealed-gate",
                    "zone_id": ZONE_ID,
                    "base_title": "The Sealed Gate",
                    "candidate_ids": ["arc-sealed-gate-alliance"],
                    "coherent_score": 4.0,
                }
            ],
            "decisions": [],
            "selected_candidate_ids_by_zone": {ZONE_ID: ["arc-sealed-gate-alliance"]},
            "family_rankings_by_zone": {ZONE_ID: ["family-sealed-gate"]},
            "coverage": [
                {
                    "zone_id": ZONE_ID,
                    "status": "coverage_met",
                    "selected_candidate_ids": ["arc-sealed-gate-alliance"],
                    "attempted_candidate_ids": ["arc-sealed-gate-alliance"],
                    "reason_codes": ["coverage_met"],
                }
            ],
            "exclusions": [],
        },
    )

    # Final CTA lint (prose finalize decisions).
    _write(
        run_root / "data" / "decisions" / "prose_finalize_decisions.json",
        {
            "schema_version": "prose_finalize_decision.v1",
            "producer": "draft_writer",
            "decisions": [
                {
                    "stage": "questline_cta.finalize",
                    "entity_id": ZONE_ID,
                    "final_lint_issues": [],
                    "fallback_used": False,
                },
                {
                    "stage": "questline_cta.finalize",
                    "entity_id": INSTANCE_ID,
                    "final_lint_issues": ["dangling_function_word"],
                    "fallback_used": True,
                },
            ],
        },
    )

    # Temporal model manifest (schema versions + model identifiers).
    _write(
        run_root / "data" / "decisions" / "temporal_model_manifest.json",
        {
            "run_id": "test-run-fake-1",
            "versions": {"entry_state_contract_version": "entry_state_contract_v2"},
        },
    )

    # Validation + fact-check reports (strict release + fact-check scope).
    _write(
        run_root / "reports" / "validate" / "validation_report.json",
        {
            "run_id": "test-run-fake-1",
            "fact_check_profile": "strict",
            "release_gate": True,
            "no_llm_fact_check": False,
            "llm_model": "gpt-5.5",
            "passed": True,
            "release_certified": True,
        },
    )
    _write(
        run_root / "reports" / "validate" / "fact_check_report.json",
        {
            "run_id": "test-run-fake-1",
            "profile": "strict",
            "llm_enabled": True,
            "target_entity_count": 1,
            "entities": [
                {"entity_id": ZONE_ID, "claim_count": 5, "review_queue": ["c-1", "c-2"]}
            ],
        },
    )


def test_build_run_quality_summary_covers_every_required_section(tmp_path: Path) -> None:
    run_root = tmp_path / "test-run-fake-1"
    _write_full_run(run_root)
    summary = build_run_quality_summary(run_root)

    assert summary["schema_version"] == QUALITY_SUMMARY_SCHEMA
    assert summary["run_id"] == "test-run-fake-1"
    assert summary["page_counts"] == {"zone_pages": 1, "instance_pages": 1}

    kinds = summary["selected_card_kinds"]
    assert kinds["by_card_type"] == {"location": 1, "faction": 1}
    assert kinds["location_entity_kinds"] == {"place": 1}
    assert kinds["key_character_entity_kinds"] == {"named_actor": 1}

    coverage = summary["direct_evidence_coverage"]
    assert coverage["packs_total"] == 2
    assert coverage["with_direct_identity"] == 1
    assert coverage["insufficient"] == 1
    assert coverage["coverage_ratio"] == 0.5

    deferred = summary["deferred_retrieval_reasons"]["location"]
    assert deferred["deferred"][0]["location_id"] == "location-north-road"
    assert deferred["rejected"][0]["reason_codes"] == ["not_a_place"]
    assert deferred["coverage"][0]["status"] == "coverage_met"

    setup = summary["questline_setup_coverage"]["entities"][0]
    assert setup["entity_id"] == ZONE_ID
    assert setup["setup_cluster_count"] == 1
    assert setup["setup_anchors_with_snippets"] == 1
    assert setup["active_expansion_status"] == "resolved"

    arc = summary["arc_family_variant_coverage"]
    assert arc["families_total"] == 1
    assert arc["candidates_total"] == 1
    assert arc["variant_candidates_selected"] == 1
    assert arc["coverage"][0]["status"] == "coverage_met"

    assert summary["title_collisions"] == []

    cta = summary["final_cta_lint"]
    assert cta["records_total"] == 2
    assert cta["fallback_used"] == 1
    assert cta["failed"][0]["entity_id"] == INSTANCE_ID

    fact_check = summary["fact_check"]
    assert fact_check["profile"] == "strict"
    assert fact_check["entities"][0]["review_queue_count"] == 2

    release = summary["strict_release"]
    assert release["release_certified"] is True
    assert release["release_gate"] is True

    versions = summary["schema_versions"]
    assert versions["location_selection"] == "location_selection.v1"
    assert versions["card_evidence_pack"] == "card_evidence_pack.v1"
    assert versions["questline_arc_selection"] == "questline_arc_selection.v1"
    assert versions["temporal_model_manifest"] == {
        "entry_state_contract_version": "entry_state_contract_v2"
    }

    hashes = summary["source_input_hashes"]
    assert hashes["source_manifest_sha256"].startswith("sha256:")
    assert hashes["manifest_identity"]["manifest_run_id"] == "manifest-fake-v1"
    assert hashes["snapshot_count"] == 1
    assert hashes["snapshot_revision_ids"] == ["mw:101"]

    model = summary["model_prompt_identifiers"]
    assert model["fact_check_llm_model"] == "gpt-5.5"
    assert model["no_llm_fact_check"] is False


def test_quality_summary_flags_title_collisions(tmp_path: Path) -> None:
    run_root = tmp_path / "test-run-fake-collide"
    _write_full_run(run_root)
    # Two cards with the same normalized base title in the same zone.
    metadata_path = run_root / "data" / "discovery" / "zone_questline_card_metadata.json"
    blob = json.loads(metadata_path.read_text(encoding="utf-8"))
    blob["metadata"].append(
        {
            "schema_version": "questline_card_metadata.v2",
            "metadata_id": "metadata-sealed-gate-2",
            "zone_id": ZONE_ID,
            "cluster_id": "cluster-sealed-gate-b",
            "source_arc_id": "arc-sealed-gate-b",
            "card_id": "cluster-sealed-gate-b",
            "canonical_id": "cluster-sealed-gate-b",
            "base_title": "The Sealed Gate",
            "faction": "alliance",
            "start_anchor": "A Vigil Begins",
            "start_anchor_ref": "quest-vigil-b",
            "chain_refs": ["quest-vigil-b"],
            "algorithm_version": "arc-v1",
        }
    )
    metadata_path.write_text(json.dumps(blob, indent=2), encoding="utf-8")

    summary = build_run_quality_summary(run_root)
    collisions = summary["title_collisions"]
    assert len(collisions) == 1
    assert collisions[0]["normalized_label"] == "the sealed gate"
    assert collisions[0]["card_ids"] == ["cluster-sealed-gate", "cluster-sealed-gate-b"]


def test_build_run_quality_summary_tolerates_minimal_run(tmp_path: Path) -> None:
    run_root = tmp_path / "test-run-fake-empty"
    _write(run_root / "data" / "drafts" / "zone_page" / f"{ZONE_ID}.json", {"zone_id": ZONE_ID})
    summary = build_run_quality_summary(run_root)
    assert summary["schema_version"] == QUALITY_SUMMARY_SCHEMA
    assert summary["run_id"] == "test-run-fake-empty"
    assert summary["selected_card_kinds"]["by_card_type"] == {}
    assert summary["direct_evidence_coverage"]["packs_total"] == 0
    assert summary["arc_family_variant_coverage"] == {}
    assert summary["strict_release"] == {}


def test_write_run_quality_summary_emits_json(tmp_path: Path) -> None:
    run_root = tmp_path / "test-run-fake-write"
    _write_full_run(run_root)
    out_path = write_run_quality_summary(run_root)
    assert out_path == run_root / "reports" / "run_quality_summary.json"
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["schema_version"] == QUALITY_SUMMARY_SCHEMA
