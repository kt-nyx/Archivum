"""Structural and conditional rendering validation rules."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from pipeline.common.text_sim import token_jaccard
from pipeline.contracts.models import (
    SUB_ZONE_MAX_QUESTLINE_CARDS,
    SUB_ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
    ZONE_MIN_QUESTLINE_INCLUSION_SCORE,
    Faction,
    IncludeDecision,
    InstancePage,
    SubZone,
    Zone,
    ZonePage,
)
from pipeline.generate.draft.instance_link_lint import is_generic_instance_link_summary
from pipeline.generate.draft.instance_lint import (
    is_generic_key_character_summary,
    is_generic_overview,
    lint_passthrough_fragment,
)
from pipeline.validate.types import ValidationIssue, ValidationSeverity


def _non_empty_text(value: str) -> bool:
    return bool(value.strip())


def _validate_enriched_glossary_refs(
    refs: list[Any],
    *,
    path_prefix: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not refs:
        return issues
    for index, ref in enumerate(refs):
        label = getattr(ref, "label", None)
        wiki_url = getattr(ref, "wiki_url", None)
        if not _non_empty_text(str(label or "")):
            issues.append(
                ValidationIssue(
                    code="structure.glossary_ref_missing_label",
                    message="glossary ref must include a non-empty label when present",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"{path_prefix}[{index}].label",
                )
            )
        if not _non_empty_text(str(wiki_url or "")):
            issues.append(
                ValidationIssue(
                    code="structure.glossary_ref_missing_wiki_url",
                    message="glossary ref must include a non-empty wiki_url when present",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"{path_prefix}[{index}].wiki_url",
                )
            )
    return issues


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


def _validate_zone_page(
    zone_page: ZonePage,
    *,
    validation_context: dict[str, Any] | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not _non_empty_text(zone_page.at_a_glance):
        issues.append(
            ValidationIssue(
                code="structure.required_section_empty",
                message="at_a_glance is required and must not be empty",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.at_a_glance",
            )
        )
    if not _non_empty_text(zone_page.currently):
        issues.append(
            ValidationIssue(
                code="structure.required_section_empty",
                message="currently is required and must not be empty",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.currently",
            )
        )
    if not zone_page.history_sections:
        issues.append(
            ValidationIssue(
                code="structure.required_section_empty",
                message="history_sections must include at least one section",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.history_sections",
            )
        )
    for index, card in enumerate(zone_page.major_questlines):
        if card.include_decision != IncludeDecision.INCLUDE:
            issues.append(
                ValidationIssue(
                    code="structure.zone_page_questline_inclusion_threshold",
                    message="zone_page questline cards must resolve to include",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.major_questlines[{index}].include_decision",
                )
            )
    currently_lower = zone_page.currently.lower()
    if any(
        marker in currently_lower
        for marker in ("years ago", "formerly", "during the third war", "was founded", "was established")
    ):
        issues.append(
            ValidationIssue(
                code="structure.zone_page_currently_temporal_drift",
                message="currently appears to contain historical-era framing",
                severity=ValidationSeverity.WARN,
                path="$.currently",
            )
        )
    history_blob = " ".join(section.body for section in zone_page.history_sections)
    overlap = token_jaccard(zone_page.currently, history_blob)
    if overlap >= 0.6:
        issues.append(
            ValidationIssue(
                code="structure.zone_page_currently_history_overlap",
                message="currently substantially overlaps with history_sections content",
                severity=ValidationSeverity.WARN,
                path="$.currently",
            )
        )
    history_blob_full = history_blob + " " + " ".join(section.heading for section in zone_page.history_sections)
    if "&#91;" in history_blob_full or "History 1" in history_blob_full:
        issues.append(
            ValidationIssue(
                code="structure.zone_page_history_passthrough_markers",
                message="history_sections contain raw wiki passthrough markers",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.history_sections",
            )
        )
    context = validation_context or {}
    questline_expect_include = bool(context.get("questline_expect_include"))
    if questline_expect_include and not zone_page.major_questlines:
        issues.append(
            ValidationIssue(
                code="structure.zone_page_empty_questlines",
                message="discovery marked questlines for inclusion but major_questlines is empty",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.major_questlines",
            )
        )
    location_expect_cards = int(context.get("location_expect_card_count", 0) or 0)
    if location_expect_cards > 0 and not zone_page.location_cards:
        issues.append(
            ValidationIssue(
                code="structure.zone_page_empty_locations",
                message="discovery marked locations for inclusion but location_cards is empty",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.location_cards",
            )
        )
    faction_summaries = [card.summary.strip().lower() for card in zone_page.major_factions if card.summary.strip()]
    if len(faction_summaries) != len(set(faction_summaries)) and len(faction_summaries) > 1:
        issues.append(
            ValidationIssue(
                code="structure.zone_page_duplicate_faction_summaries",
                message="major_factions contains duplicate summaries across distinct factions",
                severity=ValidationSeverity.WARN,
                path="$.major_factions",
            )
        )
    issues.extend(
        _validate_enriched_glossary_refs(
            zone_page.glossary_refs,
            path_prefix="$.glossary_refs",
        )
    )
    if zone_page.parent_continent.strip().lower() in {"", "unknown"}:
        issues.append(
            ValidationIssue(
                code="structure.zone_page_parent_continent_unresolved",
                message="parent_continent must be resolved from seed geography evidence",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.parent_continent",
            )
        )
    for index, card in enumerate(zone_page.instance_links):
        summary = card.summary.strip()
        if summary and is_generic_instance_link_summary(summary):
            issues.append(
                ValidationIssue(
                    code="structure.zone_page_generic_instance_link",
                    message="instance_links summary reads like generic stub filler",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.instance_links[{index}].summary",
                )
            )
    return issues


def _validate_instance_page(instance_page: InstancePage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not _non_empty_text(instance_page.at_a_glance):
        issues.append(
            ValidationIssue(
                code="structure.required_section_empty",
                message="at_a_glance is required and must not be empty",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.at_a_glance",
            )
        )
    if not _non_empty_text(instance_page.overview):
        issues.append(
            ValidationIssue(
                code="structure.required_section_empty",
                message="overview is required and must not be empty",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.overview",
            )
        )
    if not instance_page.history_sections:
        issues.append(
            ValidationIssue(
                code="structure.required_section_empty",
                message="history_sections must include at least one section",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.history_sections",
            )
        )
    overview = instance_page.overview.strip()
    if overview and lint_passthrough_fragment(overview):
        issues.append(
            ValidationIssue(
                code="structure.instance_page_overview_passthrough",
                message="overview reads like a copied source fragment, not synthesized prose",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.overview",
            )
        )
    if overview and is_generic_overview(overview):
        issues.append(
            ValidationIssue(
                code="structure.instance_page_generic_overview",
                message="overview reads like generic boilerplate filler",
                severity=ValidationSeverity.HARD_FAIL,
                path="$.overview",
            )
        )
    for index, section in enumerate(instance_page.history_sections):
        body = section.body.strip()
        if body and lint_passthrough_fragment(body):
            issues.append(
                ValidationIssue(
                    code="structure.instance_page_history_passthrough",
                    message="history section body reads like a copied source fragment",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.history_sections[{index}].body",
                )
            )
    for index, card in enumerate(instance_page.key_characters):
        summary = card.summary.strip()
        if summary and is_generic_key_character_summary(summary):
            issues.append(
                ValidationIssue(
                    code="structure.instance_page_generic_key_character",
                    message="key_characters summary reads like a generic stub",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.key_characters[{index}].summary",
                )
            )
    issues.extend(
        _validate_enriched_glossary_refs(
            instance_page.glossary_refs,
            path_prefix="$.glossary_refs",
        )
    )
    return issues


def validate_structural_rules(
    entity_type: str,
    parsed_entity: BaseModel,
    *,
    validation_context: dict[str, Any] | None = None,
) -> list[ValidationIssue]:
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
    if entity_type == "zone_page":
        zone_page = (
            parsed_entity
            if isinstance(parsed_entity, ZonePage)
            else ZonePage.model_validate(parsed_entity)
        )
        return _validate_zone_page(zone_page, validation_context=validation_context)
    if entity_type == "instance_page":
        instance_page = (
            parsed_entity
            if isinstance(parsed_entity, InstancePage)
            else InstancePage.model_validate(parsed_entity)
        )
        return _validate_instance_page(instance_page)
    return []
