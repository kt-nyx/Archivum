from __future__ import annotations

from pipeline.generate.draft.model_versions import (
    INTERNAL_DECISION_SIDECARS,
    build_temporal_model_manifest,
)


def test_manifest_records_versions_and_internal_schema_decision() -> None:
    manifest = build_temporal_model_manifest(run_id="run-123")

    assert manifest["run_id"] == "run-123"

    # The schema/contract decision: claim metadata stays internal, public draft JSON unchanged.
    contract = manifest["schema_contract"]
    assert contract["claim_metadata_visibility"] == "internal"
    assert contract["public_draft_json_includes_claim_metadata"] is False

    # All three named version fields (plus the routing/coverage stamps) are present and non-empty.
    versions = manifest["versions"]
    for key in (
        "entry_state_contract_version",
        "claim_extractor_version",
        "temporal_classifier_version",
        "claim_view_routing_version",
        "history_coverage_version",
    ):
        assert versions.get(key)

    # Every internal sidecar is documented with a purpose string.
    sidecars = manifest["internal_decision_sidecars"]
    assert sidecars == dict(INTERNAL_DECISION_SIDECARS)
    assert "claim_temporal_decisions.json" in sidecars
    assert all(purpose for purpose in sidecars.values())


def test_manifest_defaults_run_id_when_blank() -> None:
    assert build_temporal_model_manifest(run_id="")["run_id"] == "unknown"
