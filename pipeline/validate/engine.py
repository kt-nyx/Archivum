"""Validation engine for schema, budget, provenance, and structure policies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from pipeline.contracts.models import ENTITY_MODEL_MAP, WIKI_FIRST_ENTITY_MODEL_MAP
from pipeline.validate.rules.budget import validate_budget_rules
from pipeline.validate.rules.fact_check import validate_fact_check_rules
from pipeline.validate.rules.provenance import validate_provenance_rules
from pipeline.validate.rules.similarity import validate_similarity_rules
from pipeline.validate.rules.questline_promotion import validate_questline_promotion_rules
from pipeline.validate.rules.structure import validate_structural_rules
from pipeline.validate.types import ValidationIssue, ValidationReport, ValidationSeverity


def _format_error_path(loc: tuple[Any, ...]) -> str:
    if not loc:
        return "$"
    chunks = [str(token) for token in loc]
    return "$." + ".".join(chunks)


def _schema_issues_from_exception(exc: ValidationError) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for error in exc.errors():
        location = error.get("loc", ())
        issues.append(
            ValidationIssue(
                code="schema.invalid",
                message=error.get("msg", "invalid schema"),
                severity=ValidationSeverity.HARD_FAIL,
                path=_format_error_path(tuple(location)),
            )
        )
    return issues


def _finalize_report(
    entity_type: str,
    issues: list[ValidationIssue],
    *,
    fact_check_report: dict[str, object] | None = None,
) -> ValidationReport:
    hard_fail_count = sum(1 for issue in issues if issue.severity == ValidationSeverity.HARD_FAIL)
    warn_count = len(issues) - hard_fail_count
    return ValidationReport(
        entity_type=entity_type,
        issues=issues,
        hard_fail_count=hard_fail_count,
        warn_count=warn_count,
        passed=hard_fail_count == 0,
        fact_check_report=fact_check_report,
    )


def validate_payload(
    entity_type: str,
    payload: Mapping[str, Any],
    validation_context: Mapping[str, Any] | None = None,
) -> ValidationReport:
    """Validate a payload against canonical schema and policy rules."""
    model_type = ENTITY_MODEL_MAP.get(entity_type) or WIKI_FIRST_ENTITY_MODEL_MAP.get(entity_type)
    if model_type is None:
        unknown_issue = ValidationIssue(
            code="schema.unknown_entity_type",
            message=f"unsupported entity_type '{entity_type}'",
            severity=ValidationSeverity.HARD_FAIL,
            path="$.entity_type",
        )
        return _finalize_report(entity_type, [unknown_issue])

    parsed_entity: BaseModel
    try:
        parsed_entity = model_type.model_validate(payload)
    except ValidationError as exc:
        return _finalize_report(entity_type, _schema_issues_from_exception(exc))

    issues: list[ValidationIssue] = []
    issues.extend(
        validate_structural_rules(
            entity_type, parsed_entity, validation_context=dict(validation_context or {})
        )
    )
    issues.extend(
        validate_questline_promotion_rules(
            entity_type, parsed_entity, validation_context=dict(validation_context or {})
        )
    )
    issues.extend(validate_budget_rules(entity_type, parsed_entity, validation_context=validation_context))
    issues.extend(
        validate_provenance_rules(entity_type, parsed_entity, validation_context=validation_context)
    )
    # Anti-verbatim: narrative sections vs ingest snapshot bodies (after provenance, before
    # fact-check so downstream checks see the same payload).
    issues.extend(
        validate_similarity_rules(
            entity_type, parsed_entity, validation_context=validation_context
        )
    )
    fact_check_issues, fact_check_report = validate_fact_check_rules(
        entity_type,
        parsed_entity,
        validation_context=validation_context,
    )
    issues.extend(fact_check_issues)
    return _finalize_report(entity_type, issues, fact_check_report=fact_check_report)
