from __future__ import annotations

import json
from pathlib import Path

import pytest
from temporal_run_artifact_helpers import summarize_temporal_run_artifacts


def test_run_artifact_summary_surfaces_omissions_and_restricted_leaks(tmp_path: Path) -> None:
    """Artifact-level instrumentation separates classifier labels from synthesis failures.

    The cauldron and Hearthglen labels are classifier outputs. The missing Hearthglen final
    history is a downstream synthesis/coverage omission. The Andorhal and Lilian matches are
    restricted-label leaks into spoiler-sensitive final draft sections.
    """
    run_dir = _write_run(
        tmp_path,
        boundaries=[
            {
                "entity_id": "zone-example",
                "anchors": [{"kind": "questline_setup", "title": "Andorhal Campaign"}],
            },
            {
                "entity_id": "instance-example",
                "anchors": [{"kind": "instance_current_structure", "title": "Scholomance"}],
            },
        ],
        canonical_rows=[
            _canonical(
                "canonical-cauldron",
                "zone-example",
                "The Argent Dawn neutralized plague cauldrons across the farms.",
                temporal_scope="pre_entry_history",
                history_eligibility="history_background",
                field_name="history_digest",
            ),
            _canonical(
                "canonical-hearthglen",
                "zone-example",
                "Hearthglen now serves as the Argent Crusade staging ground.",
                temporal_scope="entry_state",
                history_eligibility="history_setup_bridge",
                field_name="history_digest",
            ),
            _canonical(
                "canonical-andorhal",
                "zone-example",
                (
                    "The armies clash for several days. "
                    "The battle ends with one faction claiming Andorhal."
                ),
                temporal_scope="active_storyline_outcome",
                history_eligibility="history_excluded_outcome",
                field_name="currently_input",
            ),
            _canonical(
                "canonical-shadow-council",
                "instance-example",
                "The Shadow Council later entered the school to seize a book.",
                temporal_scope="post_active_lore",
                history_eligibility="history_excluded_post_active",
                field_name="history_digest",
            ),
            _canonical(
                "canonical-lilian-outcome",
                "instance-example",
                "Gandling subdued Lilian Voss and she escaped afterward.",
                temporal_scope="active_storyline_outcome",
                history_eligibility="history_excluded_outcome",
                field_name="boss_pool",
            ),
        ],
        zone_draft={
            "zone_id": "zone-example",
            "currently": "The battle ends with one faction claiming Andorhal.",
            "history_sections": [
                {
                    "heading": "Cauldron Campaign",
                    "body": "The Argent Dawn neutralized plague cauldrons across the farms.",
                }
            ],
            "major_factions": [],
        },
        instance_draft={
            "instance_id": "instance-example",
            "currently": "The school remains under its headmaster.",
            "history_sections": [],
            "key_characters": [
                {
                    "name": "Lilian Voss",
                    "summary": "Gandling subdued Lilian Voss and she escaped afterward.",
                }
            ],
        },
    )

    summary = summarize_temporal_run_artifacts(run_dir)

    assert summary.boundary_anchors_by_subject["zone-example"][0]["title"] == "Andorhal Campaign"
    zone_labels = {
        row["canonical_evidence_id"]: row
        for row in summary.canonical_labels_by_subject["zone-example"]
    }
    assert zone_labels["canonical-cauldron"]["temporal_scope"] == "pre_entry_history"
    assert zone_labels["canonical-hearthglen"]["history_eligibility"] == "history_setup_bridge"

    missing_ids = {
        row["canonical_evidence_id"] for row in summary.history_eligible_missing_from_final
    }
    assert missing_ids == {"canonical-hearthglen"}

    restricted = {
        (row["canonical_evidence_id"], row["section"])
        for row in summary.restricted_evidence_in_final_text
    }
    assert restricted == {
        ("canonical-andorhal", "currently"),
        ("canonical-lilian-outcome", "characters"),
    }
    assert ("canonical-shadow-council", "history") not in restricted


def test_run_artifact_summary_reports_clean_fixture_without_mismatches(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        boundaries=[
            {
                "entity_id": "zone-example",
                "anchors": [{"kind": "questline_setup", "title": "Road Defense"}],
            }
        ],
        canonical_rows=[
            _canonical(
                "canonical-history",
                "zone-example",
                "The old road was fortified before the current fighting began.",
                temporal_scope="pre_entry_history",
                history_eligibility="history_background",
                field_name="history_digest",
            ),
            _canonical(
                "canonical-post-active",
                "zone-example",
                "A later report discusses soldiers marching elsewhere.",
                temporal_scope="post_active_lore",
                history_eligibility="history_excluded_post_active",
                field_name="history_digest",
            ),
        ],
        zone_draft={
            "zone_id": "zone-example",
            "currently": "The road is contested.",
            "history_sections": [
                {
                    "heading": "Fortified Road",
                    "body": "The old road was fortified before the current fighting began.",
                }
            ],
            "major_factions": [],
        },
    )

    summary = summarize_temporal_run_artifacts(run_dir)

    assert summary.history_eligible_missing_from_final == []
    assert summary.restricted_evidence_in_final_text == []
    assert "canonical_temporal_evidence_decisions.json" in summary.sidecars_present


def test_known_temporal_failure_labels_are_visible_in_distilled_artifact_summary(
    tmp_path: Path,
) -> None:
    """Small fixtures pin the known classifier-level labels without requiring live artifacts."""
    run_dir = _write_run(
        tmp_path,
        boundaries=[
            {
                "entity_id": "instance-example",
                "anchors": [{"kind": "instance_current_structure", "title": "Scholomance"}],
            }
        ],
        canonical_rows=[
            _canonical(
                "canonical-shadow-council",
                "instance-example",
                "The Shadow Council later entered the school to seize a book.",
                temporal_scope="post_active_lore",
                history_eligibility="history_excluded_post_active",
                field_name="history_digest",
            ),
            _canonical(
                "canonical-lilian-completion",
                "instance-example",
                "Adventurers defeated Gandling and Lilian Voss escaped.",
                temporal_scope="active_storyline_outcome",
                history_eligibility="history_excluded_outcome",
                field_name="history_digest",
            ),
        ],
        instance_draft={
            "instance_id": "instance-example",
            "currently": "The school remains active.",
            "history_sections": [],
            "key_characters": [],
        },
    )

    summary = summarize_temporal_run_artifacts(run_dir)
    labels = {
        row["canonical_evidence_id"]: row
        for row in summary.canonical_labels_by_subject["instance-example"]
    }

    assert labels["canonical-shadow-council"]["temporal_scope"] == "post_active_lore"
    assert labels["canonical-lilian-completion"]["temporal_scope"] == "active_storyline_outcome"
    assert summary.restricted_evidence_in_final_text == []


@pytest.mark.xfail(
    strict=True,
    reason="Claim extraction lands in later slices; paragraph-level labels cannot split mixed claims.",
)
def test_mixed_setup_and_outcome_paragraph_requires_future_claim_split(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        boundaries=[
            {
                "entity_id": "zone-example",
                "anchors": [{"kind": "questline_setup", "title": "Restoration Effort"}],
            }
        ],
        canonical_rows=[
            _canonical(
                "canonical-mixed",
                "zone-example",
                (
                    "The Cenarion Circle begins healing the fields, while the battle later "
                    "ends with one faction claiming Andorhal."
                ),
                temporal_scope="active_storyline_outcome",
                history_eligibility="history_excluded_outcome",
                field_name="history_digest",
            )
        ],
        zone_draft={
            "zone_id": "zone-example",
            "currently": "The land is wounded.",
            "history_sections": [],
            "major_factions": [],
        },
    )

    summary = summarize_temporal_run_artifacts(run_dir)

    assert "canonical_claim_extraction_decisions.json" in summary.sidecars_present
    assert not summary.history_eligible_missing_from_final


def test_claim_and_coverage_sidecars_present_when_written(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, boundaries=[], canonical_rows=[])
    decisions_dir = run_dir / "data" / "decisions"
    for sidecar in (
        "canonical_claim_extraction_decisions.json",
        "claim_temporal_decisions.json",
        "claim_view_routing_decisions.json",
        "section_coverage_decisions.json",
    ):
        _write_json(decisions_dir / sidecar, [])
    summary = summarize_temporal_run_artifacts(run_dir)

    assert "canonical_claim_extraction_decisions.json" in summary.sidecars_present
    assert "claim_temporal_decisions.json" in summary.sidecars_present
    assert "claim_view_routing_decisions.json" in summary.sidecars_present
    assert "section_coverage_decisions.json" in summary.sidecars_present


def _write_run(
    tmp_path: Path,
    *,
    boundaries: list[dict],
    canonical_rows: list[dict],
    zone_draft: dict | None = None,
    instance_draft: dict | None = None,
) -> Path:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "data" / "decisions" / "content_boundary_decisions.json",
        boundaries,
    )
    _write_json(
        run_dir / "data" / "decisions" / "canonical_temporal_evidence_decisions.json",
        canonical_rows,
    )
    _write_json(run_dir / "data" / "decisions" / "temporal_evidence_decisions.json", [])
    if zone_draft is not None:
        _write_json(run_dir / "data" / "drafts" / "zone_page" / "zone-example.json", zone_draft)
    if instance_draft is not None:
        _write_json(
            run_dir / "data" / "drafts" / "instance_page" / "instance-example.json",
            instance_draft,
        )
    return run_dir


def _canonical(
    canonical_evidence_id: str,
    subject_id: str,
    snippet: str,
    *,
    temporal_scope: str,
    history_eligibility: str,
    field_name: str,
) -> dict:
    return {
        "canonical_evidence_id": canonical_evidence_id,
        "subject_id": subject_id,
        "subject_type": "instance" if subject_id.startswith("instance-") else "zone",
        "source_id": f"src-{canonical_evidence_id}",
        "source_title": subject_id,
        "snippet": snippet,
        "appearances": [{"field_name": field_name}],
        "temporal_scope": temporal_scope,
        "history_eligibility": history_eligibility,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
