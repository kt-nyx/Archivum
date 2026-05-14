"""Structural and conditional rendering validation rules."""

from __future__ import annotations

from pydantic import BaseModel

from pipeline.contracts.models import (
    SUB_ZONE_MAX_QUESTLINE_CARDS,
    SUB_ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
    ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
    Faction,
    IncludeDecision,
    SubZone,
    Zone,
)
from pipeline.validate.types import ValidationIssue, ValidationSeverity


def _non_empty_text(value: str) -> bool:
    return bool(value.strip())


def _validate_zone(zone: Zone) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    required_sections = ("at_a_glance", "currently", "history")
    for section_name in required_sections:
        if not _non_empty_text(getattr(zone, section_name)):
            issues.append(
                ValidationIssue(
                    code="structure.required_section_empty",
                    message=f"{section_name} is required and must not be empty",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.{section_name}",
                )
            )

    for card in zone.major_questlines_alliance:
        if card.faction != Faction.ALLIANCE:
            issues.append(
                ValidationIssue(
                    code="structure.questline_faction_bucket",
                    message="alliance questline bucket must only contain faction=alliance cards",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines_alliance.{card.id}.faction",
                )
            )
    for card in zone.major_questlines_horde:
        if card.faction != Faction.HORDE:
            issues.append(
                ValidationIssue(
                    code="structure.questline_faction_bucket",
                    message="horde questline bucket must only contain faction=horde cards",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines_horde.{card.id}.faction",
                )
            )
    for card in zone.major_questlines_shared:
        if card.faction != Faction.SHARED:
            issues.append(
                ValidationIssue(
                    code="structure.questline_faction_bucket",
                    message="shared questline bucket must only contain faction=shared cards",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines_shared.{card.id}.faction",
                )
            )

    instance_ids = {card.id for card in zone.instances}
    for landmark in zone.major_landmarks:
        if landmark.id in instance_ids or landmark.id.startswith("instance-"):
            issues.append(
                ValidationIssue(
                    code="structure.landmarks_exclude_instances",
                    message="major_landmarks must not include instance-linked cards",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_landmarks.{landmark.id}",
                )
            )

    # Optional faction subsections should only render when non-empty.
    # We emit warnings when provenance is supplied for empty questline buckets.
    questline_buckets = (
        (
            "major_questlines_alliance",
            zone.major_questlines_alliance,
            zone.provenance.major_questlines_alliance,
        ),
        (
            "major_questlines_horde",
            zone.major_questlines_horde,
            zone.provenance.major_questlines_horde,
        ),
        (
            "major_questlines_shared",
            zone.major_questlines_shared,
            zone.provenance.major_questlines_shared,
        ),
    )
    for bucket_name, cards, provenance_map in questline_buckets:
        if not cards and provenance_map:
            issues.append(
                ValidationIssue(
                    code="structure.conditional_rendering_warning",
                    message=(
                        f"{bucket_name} has provenance entries but no cards; "
                        "optional subsections should render only "
                        "when non-empty"
                    ),
                    severity=ValidationSeverity.WARN,
                    path=f"$.provenance.{bucket_name}",
                )
            )

    zone_questline_buckets = (
        ("major_questlines_alliance", zone.major_questlines_alliance),
        ("major_questlines_horde", zone.major_questlines_horde),
        ("major_questlines_shared", zone.major_questlines_shared),
    )
    for bucket_name, cards in zone_questline_buckets:
        for index, card in enumerate(cards):
            decision = card.inclusion_decision
            base_path = f"$.{bucket_name}[{index}]"
            if decision.include_decision != IncludeDecision.INCLUDE:
                issues.append(
                    ValidationIssue(
                        code="structure.zone_questline_inclusion_threshold",
                        message="zone questline cards must resolve to include",
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"{base_path}.inclusion_decision.include_decision",
                    )
                )
            if decision.inclusion_score < ZONE_MIN_QUESTLINE_INCLUSION_SCORE:
                issues.append(
                    ValidationIssue(
                        code="structure.zone_questline_inclusion_threshold",
                        message=(
                            "zone questline inclusion score "
                            f"{decision.inclusion_score} is below required "
                            f"{ZONE_MIN_QUESTLINE_INCLUSION_SCORE}"
                        ),
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"{base_path}.inclusion_decision.inclusion_score",
                    )
                )
            if card.depends_on_parent_context and not (card.dependency_note or "").strip():
                issues.append(
                    ValidationIssue(
                        code="structure.zone_questline_dependency_note_required",
                        message=(
                            "dependency_note is required when depends_on_parent_context is true"
                        ),
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"{base_path}.dependency_note",
                    )
                )

    return issues


def _validate_sub_zone(sub_zone: SubZone) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    required_sections = ("at_a_glance", "currently", "history")
    for section_name in required_sections:
        if not _non_empty_text(getattr(sub_zone, section_name)):
            issues.append(
                ValidationIssue(
                    code="sub_zone.required_section_missing",
                    message=f"sub-zone requires non-empty '{section_name}'",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.{section_name}",
                )
            )

    required_lists = (
        ("major_characters", sub_zone.major_characters),
        ("major_landmarks", sub_zone.major_landmarks),
        ("glossary", sub_zone.glossary),
    )
    for section_name, values in required_lists:
        if not values:
            issues.append(
                ValidationIssue(
                    code="sub_zone.required_section_missing",
                    message=f"sub-zone requires non-empty '{section_name}' list",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.{section_name}",
                )
            )

    for card in sub_zone.major_questlines_alliance:
        if card.faction != Faction.ALLIANCE:
            issues.append(
                ValidationIssue(
                    code="sub_zone.questline_faction_bucket",
                    message=(
                        "alliance sub-zone questline bucket must contain faction=alliance cards"
                    ),
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines_alliance.{card.id}.faction",
                )
            )
    for card in sub_zone.major_questlines_horde:
        if card.faction != Faction.HORDE:
            issues.append(
                ValidationIssue(
                    code="sub_zone.questline_faction_bucket",
                    message="horde sub-zone questline bucket must contain faction=horde cards",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines_horde.{card.id}.faction",
                )
            )
    for card in sub_zone.major_questlines_shared:
        if card.faction != Faction.SHARED:
            issues.append(
                ValidationIssue(
                    code="sub_zone.questline_faction_bucket",
                    message="shared sub-zone questline bucket must contain faction=shared cards",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines_shared.{card.id}.faction",
                )
            )

    questline_buckets_prov = (
        (
            "major_questlines_alliance",
            sub_zone.major_questlines_alliance,
            sub_zone.provenance.major_questlines_alliance,
        ),
        (
            "major_questlines_horde",
            sub_zone.major_questlines_horde,
            sub_zone.provenance.major_questlines_horde,
        ),
        (
            "major_questlines_shared",
            sub_zone.major_questlines_shared,
            sub_zone.provenance.major_questlines_shared,
        ),
    )
    for bucket_name, cards, provenance_map in questline_buckets_prov:
        if not cards and provenance_map:
            issues.append(
                ValidationIssue(
                    code="structure.conditional_rendering_warning",
                    message=(
                        f"{bucket_name} has provenance entries but no cards; "
                        "optional subsections should render only when non-empty"
                    ),
                    severity=ValidationSeverity.WARN,
                    path=f"$.provenance.{bucket_name}",
                )
            )

    questline_cards = (
        sub_zone.major_questlines_alliance
        + sub_zone.major_questlines_horde
        + sub_zone.major_questlines_shared
    )
    if len(questline_cards) > SUB_ZONE_MAX_QUESTLINE_CARDS:
        issues.append(
            ValidationIssue(
                code="sub_zone.questline_max_cards",
                message=(
                    f"sub-zone pages support at most {SUB_ZONE_MAX_QUESTLINE_CARDS} questline cards"
                ),
                severity=ValidationSeverity.HARD_FAIL,
                path="$.major_questlines_*",
            )
        )

    for bucket_name, cards in (
        ("major_questlines_alliance", sub_zone.major_questlines_alliance),
        ("major_questlines_horde", sub_zone.major_questlines_horde),
        ("major_questlines_shared", sub_zone.major_questlines_shared),
    ):
        for index, card in enumerate(cards):
            decision = card.inclusion_decision
            base_path = f"$.{bucket_name}[{index}]"
            if decision.include_decision != IncludeDecision.INCLUDE:
                issues.append(
                    ValidationIssue(
                        code="sub_zone.inclusion_threshold",
                        message="sub-zone questline cards must resolve to include",
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"{base_path}.inclusion_decision.include_decision",
                    )
                )
            if decision.inclusion_score < SUB_ZONE_MIN_QUESTLINE_INCLUSION_SCORE:
                issues.append(
                    ValidationIssue(
                        code="sub_zone.inclusion_threshold",
                        message=(
                            "sub-zone questline inclusion score "
                            f"{decision.inclusion_score} is below required "
                            f"{SUB_ZONE_MIN_QUESTLINE_INCLUSION_SCORE}"
                        ),
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"{base_path}.inclusion_decision.inclusion_score",
                    )
                )

            if card.depends_on_parent_context and not (card.dependency_note or "").strip():
                issues.append(
                    ValidationIssue(
                        code="sub_zone.dependency_note_required",
                        message=(
                            "dependency_note is required when depends_on_parent_context is true"
                        ),
                        severity=ValidationSeverity.HARD_FAIL,
                        path=f"{base_path}.dependency_note",
                    )
                )

    return issues


def validate_structural_rules(entity_type: str, parsed_entity: BaseModel) -> list[ValidationIssue]:
    """Validate rendering and structural contract rules."""
    if entity_type == "zone":
        zone = (
            parsed_entity if isinstance(parsed_entity, Zone) else Zone.model_validate(parsed_entity)
        )
        return _validate_zone(zone)
    if entity_type == "sub_zone":
        sub_zone = (
            parsed_entity
            if isinstance(parsed_entity, SubZone)
            else SubZone.model_validate(parsed_entity)
        )
        return _validate_sub_zone(sub_zone)
    return []
