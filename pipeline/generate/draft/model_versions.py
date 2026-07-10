"""Temporal/claim data-model version stamps and the schema/contract decision record (Slice 11).

These version strings identify the temporal accuracy data model that produced a run's decision
sidecars. They exist for posterity and forensics: a sidecar set can be matched back to the model
generation that wrote it. There is deliberately no production migration path — this project is
pre-release, and the paragraph-fallback throughout the draft stage already lets every consumer run
without the claim sidecars present (an older artifact set simply takes the paragraph path).

Schema/contract decision (confirmed clarification question 5): all claim-level metadata — atomic
claims, claim temporal/spoiler labels, claim-view routing, and history coverage — is INTERNAL. It
lives only under ``data/decisions/`` and is never copied into the public addon-facing zone/instance
draft JSON. Exposing a versioned public subset (claim IDs, spoiler flags, coverage status, review
metadata) remains possible later, but must be an explicit, fixture-backed, versioned schema change.
"""

from __future__ import annotations

from typing import Any

from pipeline.generate.draft.claims import (
    CLAIM_EXTRACTOR_VERSION,
    LLM_CLAIM_EXTRACTOR_VERSION,
)

ENTRY_STATE_CONTRACT_VERSION = "entry_state_contract_v2"
ENTRY_STATE_CONTRACT_DECISION_SCHEMA = "entry_state_contract_decision.v1"
TEMPORAL_CLASSIFIER_VERSION = "claim_temporal_classifier_v1"
CLAIM_VIEW_ROUTING_VERSION = "claim_view_routing_v1"
HISTORY_COVERAGE_VERSION = "section_coverage_v1"
PROSE_FINALIZE_DECISION_SCHEMA = "prose_finalize_decision.v1"
CARD_EVIDENCE_PACK_SCHEMA = "card_evidence_pack.v1"

# Visibility of claim-level metadata relative to the public addon-facing draft JSON.
CLAIM_METADATA_VISIBILITY = "internal"

# Internal decision sidecars produced by the temporal refactor, with a one-line purpose. None of
# these are part of the public draft schema; they guide generation/review only.
INTERNAL_DECISION_SIDECARS: dict[str, str] = {
    "entry_state_contract_decisions.json": (
        "Per-subject entry-state contract — the semantic boundary the player walks into."
    ),
    "canonical_claim_extraction_decisions.json": (
        "Atomic claims extracted from each canonical paragraph (sentence- or LLM-level)."
    ),
    "claim_temporal_decisions.json": (
        "Per-claim temporal scope, history eligibility, and spoiler safety classification."
    ),
    "claim_view_routing_decisions.json": (
        "Which safe claim views are routeable to each section field (history, currently, ...)."
    ),
    "section_coverage_decisions.json": (
        "History coverage units and whether required setup-bridge claims were represented."
    ),
    "prose_finalize_decisions.json": (
        "Final prose decisions, including questline CTA lint, bounded rewrite, and fallback records."
    ),
    "card_evidence_pack_decisions.json": (
        "Per-card evidence packs: direct identity evidence, directional relationship evidence, "
        "support-checked claim views, and provenance ids for every rendered card."
    ),
}


def build_temporal_model_manifest(*, run_id: str) -> dict[str, Any]:
    """Machine-readable record of the data-model versions and the internal-only schema decision.

    Written to ``data/decisions/temporal_model_manifest.json`` so a run's decision sidecars can be
    traced back to the model generation that produced them, and so the claim-metadata visibility
    contract is recorded alongside the artifacts it governs.
    """
    return {
        "run_id": run_id or "unknown",
        "schema_contract": {
            "claim_metadata_visibility": CLAIM_METADATA_VISIBILITY,
            "public_draft_json_includes_claim_metadata": False,
            "note": (
                "Claim-level metadata is internal/sidecar-only. Exposing a public subset later "
                "requires an explicit, versioned, fixture-backed schema change."
            ),
        },
        "versions": {
            "entry_state_contract_version": ENTRY_STATE_CONTRACT_VERSION,
            "entry_state_contract_decision_schema": ENTRY_STATE_CONTRACT_DECISION_SCHEMA,
            "claim_extractor_version": CLAIM_EXTRACTOR_VERSION,
            "claim_llm_extractor_version": LLM_CLAIM_EXTRACTOR_VERSION,
            "temporal_classifier_version": TEMPORAL_CLASSIFIER_VERSION,
            "claim_view_routing_version": CLAIM_VIEW_ROUTING_VERSION,
            "history_coverage_version": HISTORY_COVERAGE_VERSION,
            "prose_finalize_decision_schema": PROSE_FINALIZE_DECISION_SCHEMA,
            "card_evidence_pack_schema": CARD_EVIDENCE_PACK_SCHEMA,
        },
        "internal_decision_sidecars": dict(INTERNAL_DECISION_SIDECARS),
    }
