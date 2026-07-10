"""Strict release-gate behavioral tests (generalization-quality-recovery Slice 8).

Every gate is exercised independently against a synthetic, generic page and hand-built
selection/evidence sidecar context — no zone/instance/title/race/species output is encoded. The
adversarial cases (wrong entity kind, mention-only identity, sidecar disagreement, malformed CTA)
mirror the acceptance criteria: the Maraudon-style generic roster (a non-named-actor key character)
and the Cenarion-Wildlands-style identity inversion (a card whose pack has no direct identity
evidence) must be rejected before a strict run can be marked successful.
"""

from __future__ import annotations

from typing import Any

from pipeline.validate.engine import validate_payload
from pipeline.validate.types import ValidationSeverity
from tests.factories.wiki_first_pages import (
    minimal_instance_page_payload,
    minimal_zone_page_payload,
)


def _ptr(source_id: str = "src-zone") -> dict[str, str]:
    return {
        "source_id": source_id,
        "locator": "section:lead paragraph:1",
        "revision_id": "mw:42",
        "excerpt_hash": "sha256:releasegate11111",
    }


def _location_card(card_id: str, *, name: str = "Redstone Keep") -> dict[str, Any]:
    return {
        "id": card_id,
        "name": name,
        "location_type": "town",
        "zone_id": "zone-testlands",
        "wiki_url": f"https://example.test/{card_id}",
        "summary": f"{name} anchors the frontier's defensive line along the main road.",
        "significance_tag": "conflict-hub",
        "provenance": [_ptr()],
    }


def _faction_card(card_id: str, *, name: str) -> dict[str, Any]:
    return {
        "id": card_id,
        "name": name,
        "summary": f"{name} coordinates patrols and shelters refugees across the frontier.",
        "wiki_url": f"https://example.test/{card_id}",
    }


def _questline_card(card_id: str) -> dict[str, Any]:
    return {
        "id": card_id,
        "title": "Frontier Reclamation",
        "faction": "alliance",
        "cta_hook": "Push the hostile line back and reopen the western supply road.",
        "start_anchor": "First Muster",
        "chain_refs": ["quest-a"],
        "include_decision": "include",
        "reason_codes": ["graph_depth"],
        "wiki_refs": ["/wiki/First_Muster"],
    }


def _character_card(card_id: str, *, role: str = "enemy") -> dict[str, Any]:
    return {
        "id": card_id,
        "name": "Warden Kaelis",
        "summary": (
            "Warden Kaelis commands the stronghold garrison and directs its ritual defenses "
            "against intruding patrols."
        ),
        "role": role,
    }


def _ok_pack(card_id: str, card_type: str) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "card_type": card_type,
        "subject_id": card_id,
        "sufficiency": "ok",
        "identity_evidence": [{"evidence_id": "e1", "role": "identity"}],
        "provenance_ids": ["e1"],
    }


def _codes(report: Any) -> set[str]:
    return {issue.code for issue in report.issues}


# --- Item 1(a): non-place location card ------------------------------------------------------


def test_release_gate_location_card_not_place_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_location_selection_by_id": {
                "location-keep": {"entity_kind": "organization", "state": "selected"},
            },
        },
    )
    assert report.passed is False
    assert "release_gate.location_card_not_place" in _codes(report)


# --- Item 2: rendered location the selection sidecar never recorded ---------------------------


def test_release_gate_location_card_unselected_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_location_selection_by_id": {
                "location-other": {"entity_kind": "place", "state": "selected"},
            },
        },
    )
    assert "release_gate.location_card_unselected" in _codes(report)


# --- Item 1(c): absent direct identity evidence ----------------------------------------------


def test_release_gate_card_missing_identity_evidence_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_card_packs_present": True,
            "release_card_evidence_packs": {
                "location-keep": {
                    "card_type": "location",
                    "subject_id": "location-keep",
                    "sufficiency": "insufficient_identity_evidence",
                    "identity_evidence": [],
                    "provenance_ids": [],
                }
            },
        },
    )
    assert report.passed is False
    assert "release_gate.card_missing_identity_evidence" in _codes(report)


def test_release_gate_card_missing_evidence_pack_orphan_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_card_packs_present": True,
            "release_card_evidence_packs": {"location-other": _ok_pack("location-other", "location")},
        },
    )
    assert "release_gate.card_missing_evidence_pack" in _codes(report)


def test_release_gate_card_pack_kind_mismatch_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_card_packs_present": True,
            # A pack typed as a faction cannot back a location card.
            "release_card_evidence_packs": {"location-keep": _ok_pack("location-keep", "faction")},
        },
    )
    assert "release_gate.card_pack_kind_mismatch" in _codes(report)


# --- Item 1(b): non-named-actor key character (Maraudon-style generic roster) -----------------


def test_release_gate_key_character_not_named_actor_hard_fails() -> None:
    payload = minimal_instance_page_payload()
    payload["key_characters"] = [_character_card("boss-kaelis")]
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_instance_decision_present": True,
            "release_instance_participants": {
                "boss-kaelis": {
                    "entity_kind": "group_or_species",
                    "retail_scope": "retail_confirmed",
                    "instance_presence_evidence": ["roster:1"],
                    "admission": "eligible",
                    "emitted": True,
                    "final_role": "enemy",
                }
            },
        },
    )
    assert report.passed is False
    assert "release_gate.key_character_not_named_actor" in _codes(report)


# --- Item 1(d): invalid instance-presence / retail-scope data --------------------------------


def test_release_gate_key_character_invalid_instance_scope_hard_fails() -> None:
    payload = minimal_instance_page_payload()
    payload["key_characters"] = [_character_card("boss-kaelis")]
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_instance_decision_present": True,
            "release_instance_participants": {
                "boss-kaelis": {
                    "entity_kind": "named_actor",
                    "retail_scope": "unknown",
                    "instance_presence_evidence": [],
                    "admission": "eligible",
                    "emitted": True,
                    "final_role": "enemy",
                }
            },
        },
    )
    assert "release_gate.key_character_invalid_instance_scope" in _codes(report)


# --- Item 2: key-character sidecar disagreement ----------------------------------------------


def test_release_gate_key_character_unselected_hard_fails() -> None:
    payload = minimal_instance_page_payload()
    payload["key_characters"] = [_character_card("boss-kaelis")]
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_instance_decision_present": True,
            "release_instance_participants": {
                "boss-other": {
                    "entity_kind": "named_actor",
                    "retail_scope": "retail_confirmed",
                    "instance_presence_evidence": ["roster:1"],
                    "admission": "eligible",
                    "emitted": True,
                    "final_role": "enemy",
                }
            },
        },
    )
    assert "release_gate.key_character_unselected" in _codes(report)


def test_release_gate_key_character_role_mismatch_hard_fails() -> None:
    payload = minimal_instance_page_payload()
    payload["key_characters"] = [_character_card("boss-kaelis", role="ally")]
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_instance_decision_present": True,
            "release_instance_participants": {
                "boss-kaelis": {
                    "entity_kind": "named_actor",
                    "retail_scope": "retail_confirmed",
                    "instance_presence_evidence": ["roster:1"],
                    "admission": "eligible",
                    "emitted": True,
                    "final_role": "enemy",
                }
            },
        },
    )
    assert "release_gate.key_character_role_mismatch" in _codes(report)


# --- Item 1(f): empty required questline setup evidence --------------------------------------


def test_release_gate_questline_setup_evidence_empty_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["major_questlines"] = [_questline_card("ql-arc-1")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_entry_state_present": True,
            "release_questline_setup_clusters": set(),
            "questline_card_metadata_by_cluster": {"cluster-arc-1": {"card_id": "ql-arc-1"}},
        },
    )
    assert report.passed is False
    assert "release_gate.questline_setup_evidence_empty" in _codes(report)


def test_release_gate_questline_setup_evidence_present_passes() -> None:
    payload = minimal_zone_page_payload()
    payload["major_questlines"] = [_questline_card("ql-arc-1")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_entry_state_present": True,
            "release_questline_setup_clusters": {"cluster-arc-1"},
            "questline_card_metadata_by_cluster": {"cluster-arc-1": {"card_id": "ql-arc-1"}},
        },
    )
    assert "release_gate.questline_setup_evidence_empty" not in _codes(report)


# --- Item 1(h): failed final CTA lint --------------------------------------------------------


def test_release_gate_questline_cta_lint_failed_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={"release_gate": True, "release_cta_lint_failed": True},
    )
    assert report.passed is False
    assert "release_gate.questline_cta_lint_failed" in _codes(report)


# --- Item 1(g): duplicate normalized card labels --------------------------------------------


def test_release_gate_duplicate_card_label_hard_fails() -> None:
    payload = minimal_zone_page_payload()
    payload["major_factions"] = [
        _faction_card("faction-a", name="Crimson Vanguard"),
        _faction_card("faction-b", name="crimson  vanguard"),
    ]
    payload["provenance"]["major_factions"] = {
        "faction-a": [_ptr()],
        "faction-b": [_ptr()],
    }
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={"release_gate": True},
    )
    assert report.passed is False
    assert "release_gate.duplicate_card_label" in _codes(report)


# --- Sidecar-gated no-op + positive control --------------------------------------------------


def test_release_gate_no_op_when_sidecars_absent() -> None:
    """A card present with release_gate on but no selection/evidence sidecar loaded must not
    invent a failure — the gate is sidecar-gated."""
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={"release_gate": True},
    )
    assert not any(code.startswith("release_gate.") for code in _codes(report))


def test_release_gate_consistent_location_card_passes_gate() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_card_packs_present": True,
            "release_card_evidence_packs": {"location-keep": _ok_pack("location-keep", "location")},
            "release_location_selection_by_id": {
                "location-keep": {"entity_kind": "place", "state": "selected"},
            },
        },
    )
    assert not any(code.startswith("release_gate.") for code in _codes(report))


def test_release_gate_inactive_without_release_gate_flag() -> None:
    payload = minimal_instance_page_payload()
    payload["key_characters"] = [_character_card("boss-kaelis")]
    report = validate_payload(
        "instance_page",
        payload,
        validation_context={
            # No release_gate: exploration profile is not held to the strict contracts.
            "release_instance_decision_present": True,
            "release_instance_participants": {
                "boss-kaelis": {"entity_kind": "group_or_species"},
            },
        },
    )
    assert not any(code.startswith("release_gate.") for code in _codes(report))


def test_release_gate_severity_is_hard_fail() -> None:
    payload = minimal_zone_page_payload()
    payload["location_cards"] = [_location_card("location-keep")]
    report = validate_payload(
        "zone_page",
        payload,
        validation_context={
            "release_gate": True,
            "release_location_selection_by_id": {
                "location-keep": {"entity_kind": "object_or_concept", "state": "selected"},
            },
        },
    )
    gate_issues = [i for i in report.issues if i.code.startswith("release_gate.")]
    assert gate_issues
    assert all(i.severity == ValidationSeverity.HARD_FAIL for i in gate_issues)
