"""Provenance validation rules."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from pipeline.contracts.models import (
    Asset,
    Character,
    GlossaryTerm,
    Instance,
    SourceManifestEntry,
    SourcePointer,
    SubZone,
    Zone,
)
from pipeline.validate.types import ValidationIssue, ValidationSeverity

WORD_RE = re.compile(r"\b[\w']+\b")


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _required_pointer_count(word_count: int) -> int:
    if word_count <= 120:
        return 1
    if word_count <= 240:
        return 2
    return 3


def _validate_pointer_set(
    pointers: list[SourcePointer],
    *,
    source_ids: set[str],
    min_count: int,
    path: str,
    code: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(pointers) < min_count:
        issues.append(
            ValidationIssue(
                code=code,
                message=f"requires at least {min_count} source pointer(s), got {len(pointers)}",
                severity=ValidationSeverity.HARD_FAIL,
                path=path,
            )
        )
    for index, pointer in enumerate(pointers):
        if pointer.source_id not in source_ids:
            issues.append(
                ValidationIssue(
                    code="provenance.unknown_source_id",
                    message=f"source_id '{pointer.source_id}' not found in sources[] manifest",
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"{path}[{index}].source_id",
                )
            )
    return issues


def _source_revision_map(source_manifest: Sequence[SourceManifestEntry]) -> dict[str, str]:
    revision_map: dict[str, str] = {}
    for source in source_manifest:
        source_id = source.source_id
        revision_id = source.revision_id
        if isinstance(revision_id, str) and revision_id.strip():
            revision_map[source_id] = revision_id
    return revision_map


def _stale_revision_issues(
    pointers: list[SourcePointer], *, source_revisions: dict[str, str], path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, pointer in enumerate(pointers):
        expected_revision = source_revisions.get(pointer.source_id)
        if expected_revision and pointer.revision_id != expected_revision:
            issues.append(
                ValidationIssue(
                    code="provenance.stale_source_revision",
                    message=(
                        f"pointer revision_id '{pointer.revision_id}' does not match manifest "
                        f"revision_id '{expected_revision}' for source_id '{pointer.source_id}'"
                    ),
                    severity=ValidationSeverity.WARN,
                    path=f"{path}[{index}].revision_id",
                )
            )
    return issues


def _mixed_source_recommendation_issue(
    pointers: list[SourcePointer], *, min_count: int, path: str
) -> ValidationIssue | None:
    if min_count < 2:
        return None
    unique_sources = {pointer.source_id for pointer in pointers}
    if len(unique_sources) >= 2:
        return None
    return ValidationIssue(
        code="provenance.mixed_source_recommended",
        message=(
            "section meets minimum pointers but only references one source_id; "
            "mixed-source coverage is recommended"
        ),
        severity=ValidationSeverity.WARN,
        path=path,
    )


def _validate_asset(asset: Asset) -> list[ValidationIssue]:
    """Validate asset provenance with the same manifest semantics as other entities."""
    issues: list[ValidationIssue] = []
    source_ids = {source.source_id for source in asset.sources}
    source_revisions = _source_revision_map(asset.sources)
    caption_body = asset.caption or ""
    caption_words = _word_count(caption_body)
    caption_pointers = asset.provenance.caption

    if caption_body.strip():
        min_caption = _required_pointer_count(caption_words)
        issues.extend(
            _validate_pointer_set(
                caption_pointers,
                source_ids=source_ids,
                min_count=min_caption,
                path="$.provenance.caption",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                caption_pointers, source_revisions=source_revisions, path="$.provenance.caption"
            )
        )
        mixed_source_issue = _mixed_source_recommendation_issue(
            caption_pointers,
            min_count=min_caption,
            path="$.provenance.caption",
        )
        if mixed_source_issue:
            issues.append(mixed_source_issue)
    elif caption_pointers:
        issues.append(
            ValidationIssue(
                code="provenance.optional_section_warning",
                message=(
                    "caption provenance pointers are present but caption body is empty; "
                    "optional fields should omit pointers when unused"
                ),
                severity=ValidationSeverity.WARN,
                path="$.provenance.caption",
            )
        )
        issues.extend(
            _validate_pointer_set(
                caption_pointers,
                source_ids=source_ids,
                min_count=0,
                path="$.provenance.caption",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                caption_pointers, source_revisions=source_revisions, path="$.provenance.caption"
            )
        )

    audit_blob = f"{asset.title}\n{asset.allowed_use_reason}\n{asset.proof_ref}"
    min_meta = _required_pointer_count(_word_count(audit_blob))
    issues.extend(
        _validate_pointer_set(
            asset.provenance.metadata,
            source_ids=source_ids,
            min_count=min_meta,
            path="$.provenance.metadata",
            code="provenance.missing_section_pointers",
        )
    )
    issues.extend(
        _stale_revision_issues(
            asset.provenance.metadata,
            source_revisions=source_revisions,
            path="$.provenance.metadata",
        )
    )
    mixed_source_issue = _mixed_source_recommendation_issue(
        asset.provenance.metadata,
        min_count=min_meta,
        path="$.provenance.metadata",
    )
    if mixed_source_issue:
        issues.append(mixed_source_issue)
    return issues


def _validate_zone(zone: Zone) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source_ids = {source.source_id for source in zone.sources}
    source_revisions = _source_revision_map(zone.sources)

    sections = {
        "at_a_glance": zone.at_a_glance,
        "currently": zone.currently,
        "history": zone.history,
    }
    for section_name, section_text in sections.items():
        pointers = getattr(zone.provenance, section_name)
        min_count = _required_pointer_count(_word_count(section_text))
        issues.extend(
            _validate_pointer_set(
                pointers,
                source_ids=source_ids,
                min_count=min_count,
                path=f"$.provenance.{section_name}",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                pointers,
                source_revisions=source_revisions,
                path=f"$.provenance.{section_name}",
            )
        )
        mixed_source_issue = _mixed_source_recommendation_issue(
            pointers,
            min_count=min_count,
            path=f"$.provenance.{section_name}",
        )
        if mixed_source_issue:
            issues.append(mixed_source_issue)

    def validate_group(group_name: str, card_ids: list[str]) -> None:
        pointer_map: dict[str, list[SourcePointer]] = getattr(zone.provenance, group_name)
        for card_id in card_ids:
            issues.extend(
                _validate_pointer_set(
                    pointer_map.get(card_id, []),
                    source_ids=source_ids,
                    min_count=1,
                    path=f"$.provenance.{group_name}.{card_id}",
                    code="provenance.missing_card_pointers",
                )
            )

    validate_group(
        "major_questlines_alliance", [card.id for card in zone.major_questlines_alliance]
    )
    validate_group("major_questlines_horde", [card.id for card in zone.major_questlines_horde])
    validate_group("major_questlines_shared", [card.id for card in zone.major_questlines_shared])
    validate_group("major_characters", [card.id for card in zone.major_characters])
    validate_group("instances", [card.id for card in zone.instances])
    validate_group("major_landmarks", [card.id for card in zone.major_landmarks])
    validate_group("glossary", [link.term_id for link in zone.glossary])
    return issues


def _validate_instance(instance: Instance) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source_ids = {source.source_id for source in instance.sources}
    source_revisions = _source_revision_map(instance.sources)

    for section_name in ("identity_header", "story_context"):
        section_text = getattr(instance, section_name)
        pointers = getattr(instance.provenance, section_name)
        min_count = _required_pointer_count(_word_count(section_text))
        issues.extend(
            _validate_pointer_set(
                pointers,
                source_ids=source_ids,
                min_count=min_count,
                path=f"$.provenance.{section_name}",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                pointers,
                source_revisions=source_revisions,
                path=f"$.provenance.{section_name}",
            )
        )
        mixed_source_issue = _mixed_source_recommendation_issue(
            pointers,
            min_count=min_count,
            path=f"$.provenance.{section_name}",
        )
        if mixed_source_issue:
            issues.append(mixed_source_issue)
    for card in instance.key_characters:
        issues.extend(
            _validate_pointer_set(
                instance.provenance.key_characters.get(card.id, []),
                source_ids=source_ids,
                min_count=1,
                path=f"$.provenance.key_characters.{card.id}",
                code="provenance.missing_card_pointers",
            )
        )
    return issues


def _validate_sub_zone(sub_zone: SubZone) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source_ids = {source.source_id for source in sub_zone.sources}
    source_revisions = _source_revision_map(sub_zone.sources)

    sections = {
        "at_a_glance": sub_zone.at_a_glance,
        "currently": sub_zone.currently,
        "history": sub_zone.history,
    }
    for section_name, section_text in sections.items():
        pointers = getattr(sub_zone.provenance, section_name)
        min_count = _required_pointer_count(_word_count(section_text))
        issues.extend(
            _validate_pointer_set(
                pointers,
                source_ids=source_ids,
                min_count=min_count,
                path=f"$.provenance.{section_name}",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                pointers,
                source_revisions=source_revisions,
                path=f"$.provenance.{section_name}",
            )
        )
        mixed_source_issue = _mixed_source_recommendation_issue(
            pointers,
            min_count=min_count,
            path=f"$.provenance.{section_name}",
        )
        if mixed_source_issue:
            issues.append(mixed_source_issue)

    def validate_group(group_name: str, card_ids: list[str]) -> None:
        pointer_map: dict[str, list[SourcePointer]] = getattr(sub_zone.provenance, group_name)
        for card_id in card_ids:
            issues.extend(
                _validate_pointer_set(
                    pointer_map.get(card_id, []),
                    source_ids=source_ids,
                    min_count=1,
                    path=f"$.provenance.{group_name}.{card_id}",
                    code="provenance.missing_card_pointers",
                )
            )

    validate_group(
        "major_questlines_alliance", [card.id for card in sub_zone.major_questlines_alliance]
    )
    validate_group("major_questlines_horde", [card.id for card in sub_zone.major_questlines_horde])
    validate_group(
        "major_questlines_shared", [card.id for card in sub_zone.major_questlines_shared]
    )
    validate_group("major_characters", [card.id for card in sub_zone.major_characters])
    validate_group("instances", [card.id for card in sub_zone.instances])
    validate_group("major_landmarks", [card.id for card in sub_zone.major_landmarks])
    validate_group("glossary", [link.term_id for link in sub_zone.glossary])
    return issues


def _validate_character(character: Character) -> list[ValidationIssue]:
    source_ids = {source.source_id for source in character.sources}
    source_revisions = _source_revision_map(character.sources)
    issues: list[ValidationIssue] = []
    for section_name in ("summary", "short_history"):
        section_value = getattr(character, section_name)
        pointers = getattr(character.provenance, section_name)
        min_count = _required_pointer_count(_word_count(section_value))
        issues.extend(
            _validate_pointer_set(
                pointers,
                source_ids=source_ids,
                min_count=min_count,
                path=f"$.provenance.{section_name}",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                pointers,
                source_revisions=source_revisions,
                path=f"$.provenance.{section_name}",
            )
        )
        mixed_source_issue = _mixed_source_recommendation_issue(
            pointers,
            min_count=min_count,
            path=f"$.provenance.{section_name}",
        )
        if mixed_source_issue:
            issues.append(mixed_source_issue)
    return issues


def _validate_glossary_term(term: GlossaryTerm) -> list[ValidationIssue]:
    source_ids = {source.source_id for source in term.sources}
    source_revisions = _source_revision_map(term.sources)
    issues: list[ValidationIssue] = []
    for section_name in ("summary", "brief_history"):
        section_value = getattr(term, section_name)
        pointers = getattr(term.provenance, section_name)
        min_count = _required_pointer_count(_word_count(section_value))
        issues.extend(
            _validate_pointer_set(
                pointers,
                source_ids=source_ids,
                min_count=min_count,
                path=f"$.provenance.{section_name}",
                code="provenance.missing_section_pointers",
            )
        )
        issues.extend(
            _stale_revision_issues(
                pointers,
                source_revisions=source_revisions,
                path=f"$.provenance.{section_name}",
            )
        )
        mixed_source_issue = _mixed_source_recommendation_issue(
            pointers,
            min_count=min_count,
            path=f"$.provenance.{section_name}",
        )
        if mixed_source_issue:
            issues.append(mixed_source_issue)
    return issues


def _release_gate_override_issues(
    validation_context: Mapping[str, Any] | None,
) -> list[ValidationIssue]:
    if not validation_context:
        return []
    if not bool(validation_context.get("release_gate", False)):
        return []
    if not bool(validation_context.get("unresolved_provenance_override", False)):
        return []
    return [
        ValidationIssue(
            code="provenance.unresolved_override_release_gate",
            message=(
                "unresolved provenance override is not allowed at release gate and must block"
            ),
            severity=ValidationSeverity.HARD_FAIL,
            path="$.provenance_overrides",
        )
    ]


def validate_provenance_rules(
    entity_type: str,
    parsed_entity: BaseModel,
    validation_context: Mapping[str, Any] | None = None,
) -> list[ValidationIssue]:
    """Run provenance checks for the parsed entity."""
    issues: list[ValidationIssue] = []
    if entity_type == "zone":
        issues.extend(
            _validate_zone(
                parsed_entity
                if isinstance(parsed_entity, Zone)
                else Zone.model_validate(parsed_entity)
            )
        )
    elif entity_type == "instance":
        issues.extend(
            _validate_instance(
                parsed_entity
                if isinstance(parsed_entity, Instance)
                else Instance.model_validate(parsed_entity)
            )
        )
    elif entity_type == "character":
        issues.extend(
            _validate_character(
                parsed_entity
                if isinstance(parsed_entity, Character)
                else Character.model_validate(parsed_entity)
            )
        )
    elif entity_type == "sub_zone":
        issues.extend(
            _validate_sub_zone(
                parsed_entity
                if isinstance(parsed_entity, SubZone)
                else SubZone.model_validate(parsed_entity)
            )
        )
    elif entity_type == "glossary_term":
        issues.extend(
            _validate_glossary_term(
                parsed_entity
                if isinstance(parsed_entity, GlossaryTerm)
                else GlossaryTerm.model_validate(parsed_entity)
            )
        )
    elif entity_type == "asset":
        asset_entity = (
            parsed_entity
            if isinstance(parsed_entity, Asset)
            else Asset.model_validate(parsed_entity)
        )
        issues.extend(_validate_asset(asset_entity))

    issues.extend(_release_gate_override_issues(validation_context))
    return issues
