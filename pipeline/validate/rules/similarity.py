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
    sections = _narrative_section_names(entity_type)
    if not sections:
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
        for name in sections
    )
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

    for section_name in sections:
        text_value = payload.get(section_name)
        if not isinstance(text_value, str) or not text_value.strip():
            continue
        source_ids = _section_pointer_source_ids(payload, section_name)
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
