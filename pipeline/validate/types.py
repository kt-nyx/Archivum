"""Shared validation report and issue types."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ValidationSeverity(StrEnum):
    HARD_FAIL = "hard-fail"
    WARN = "warn"


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: ValidationSeverity
    path: str


class ValidationReport(BaseModel):
    entity_type: str
    issues: list[ValidationIssue]
    hard_fail_count: int
    warn_count: int
    passed: bool
    fact_check_report: dict[str, object] | None = None
