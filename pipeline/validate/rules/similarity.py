"""Anti-verbatim similarity checks against ingest snapshot bodies (MP3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from pipeline.validate.types import ValidationIssue, ValidationSeverity
from pipeline.validate.validate_similarity import max_similarity_against_sources

# Token-set Jaccard (`max_similarity_against_sources`) between a narrative section
# and provenance-linked snapshot `body` text. Tuned conservatively: warn on elevated
# overlap, hard-fail only on very high overlap suggestive of copy-paste.
SIMILARITY_WARN_THRESHOLD = 0.50
SIMILARITY_HARD_FAIL_THRESHOLD = 0.72

# Truncate very long wiki bodies for stable cost and to emphasize local overlap.
_MAX_SOURCE_BODY_CHARS = 6000


def _ingest_unavailable_severity(
    validation_context: Mapping[str, Any] | None,
) -> ValidationSeverity:
    """strict: missing ingest bodies → hard-fail; warn: advisory (anti-verbatim cannot run)."""
    if not validation_context:
        return ValidationSeverity.WARN
    raw = validation_context.get("fact_check_profile", "warn")
    profile = raw.strip().lower() if isinstance(raw, str) else "warn"
    if profile == "strict":
        return ValidationSeverity.HARD_FAIL
    return ValidationSeverity.WARN


def _narrative_section_names(entity_type: str) -> tuple[str, ...]:
    """Same narrative fields as fact-check uses for claim-style sections."""
    if entity_type in {"zone", "sub_zone"}:
        return ("at_a_glance", "currently", "history")
    if entity_type == "instance":
        return ("identity_header", "story_context")
    if entity_type == "character":
        return ("summary", "short_history")
    if entity_type == "glossary_term":
        return ("summary", "brief_history")
    if entity_type == "zone_page":
        return ("at_a_glance", "currently")
    if entity_type == "instance_page":
        return ("at_a_glance", "overview")
    return ()


def _section_pointer_source_ids(payload: dict[str, Any], section_name: str) -> list[str]:
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return []
    section_pointers = provenance.get(section_name)
    if not isinstance(section_pointers, list):
        return []
    source_ids: list[str] = []
    for pointer in section_pointers:
        if not isinstance(pointer, dict):
            continue
        source_id = pointer.get("source_id")
        if isinstance(source_id, str) and source_id:
            source_ids.append(source_id)
    return source_ids


def _snapshot_bodies_by_source_id(
    validation_context: Mapping[str, Any] | None,
) -> dict[str, str]:
    if not validation_context:
        return {}
    snapshots = validation_context.get("fact_check_source_snapshots")
    if not isinstance(snapshots, list):
        return {}
    bodies: dict[str, str] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        source_id = snapshot.get("source_id")
        body = snapshot.get("body")
        if isinstance(source_id, str) and source_id and isinstance(body, str) and body.strip():
            bodies[source_id] = body[:_MAX_SOURCE_BODY_CHARS]
    return bodies


def validate_similarity_rules(
    entity_type: str,
    parsed_entity: BaseModel,
    *,
    validation_context: Mapping[str, Any] | None = None,
) -> list[ValidationIssue]:
    """Compare narrative draft sections to ingest bodies linked by provenance."""
    scalar_sections = _narrative_section_names(entity_type)
    has_history_list = entity_type in {"zone_page", "instance_page"}
    if not scalar_sections and not has_history_list:
        return []

    payload = parsed_entity.model_dump(mode="python")
    issues: list[ValidationIssue] = []

    body_by_source = _snapshot_bodies_by_source_id(validation_context)
    raw_snapshots = (
        validation_context.get("fact_check_source_snapshots")
        if validation_context
        else None
    )
    snapshots_unusable = (
        not validation_context
        or not isinstance(raw_snapshots, list)
        or len(raw_snapshots) == 0
        or not body_by_source
    )

    has_any_narrative = any(
        isinstance(payload.get(name), str) and str(payload.get(name, "")).strip()
        for name in scalar_sections
    )
    if has_history_list and isinstance(payload.get("history_sections"), list):
        has_any_narrative = has_any_narrative or bool(payload.get("history_sections"))
    require_snapshots = bool(
        validation_context and validation_context.get("similarity_require_snapshots")
    )
    if has_any_narrative and snapshots_unusable:
        if require_snapshots:
            issues.append(
                ValidationIssue(
                    code="similarity.ingest_snapshots_unavailable",
                    message=(
                        "Similarity check skipped ingest bodies: "
                        "fact_check_source_snapshots missing, empty, or without usable body text"
                    ),
                    severity=_ingest_unavailable_severity(validation_context),
                    path="$.provenance",
                )
            )
        return issues

    section_entries: list[tuple[str, str, list[str]]] = []
    for section_name in scalar_sections:
        text_value = payload.get(section_name)
        if not isinstance(text_value, str) or not text_value.strip():
            continue
        source_ids = _section_pointer_source_ids(payload, section_name)
        if entity_type == "instance_page":
            if section_name == "at_a_glance":
                source_ids = _section_pointer_source_ids(payload, "identity_header")
            elif section_name == "overview":
                source_ids = _section_pointer_source_ids(payload, "story_context")
        section_entries.append((section_name, text_value, source_ids))
    if has_history_list:
        history_sections = payload.get("history_sections")
        if isinstance(history_sections, list):
            history_source_ids = _section_pointer_source_ids(payload, "history")
            for index, history_row in enumerate(history_sections):
                if not isinstance(history_row, dict):
                    continue
                body = history_row.get("body")
                if not isinstance(body, str) or not body.strip():
                    continue
                section_entries.append((f"history_sections[{index}].body", body, history_source_ids))

    for section_name, text_value, source_ids in section_entries:
        snippets = [body_by_source[sid] for sid in source_ids if sid in body_by_source]
        if not snippets and source_ids:
            issues.append(
                ValidationIssue(
                    code="similarity.snapshot_body_missing_for_section",
                    message=(
                        f"No ingest body available for provenance source_ids in "
                        f"'{section_name}' (similarity not evaluated against wiki text)"
                    ),
                    severity=ValidationSeverity.WARN,
                    path=f"$.{section_name}",
                )
            )
            continue
        if not snippets:
            continue

        score = max_similarity_against_sources(text_value, snippets)
        if score >= SIMILARITY_HARD_FAIL_THRESHOLD:
            issues.append(
                ValidationIssue(
                    code="similarity.verbatim_overlap_hard",
                    message=(
                        f"Very high token overlap ({score:.2f}) between '{section_name}' "
                        f"and ingest source body; revise for non-verbatim paraphrase"
                    ),
                    severity=ValidationSeverity.HARD_FAIL,
                    path=f"$.{section_name}",
                )
            )
        elif score >= SIMILARITY_WARN_THRESHOLD:
            issues.append(
                ValidationIssue(
                    code="similarity.verbatim_overlap_warn",
                    message=(
                        f"Elevated token overlap ({score:.2f}) between '{section_name}' "
                        f"and ingest source body; consider rephrasing"
                    ),
                    severity=ValidationSeverity.WARN,
                    path=f"$.{section_name}",
                )
            )

    return issues
