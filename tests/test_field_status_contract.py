"""Phase 1d failure-sentinel contract: null prose + field_status validates and renders as omission.

A field whose live synthesis fails after retries is emitted as ``null`` with the reason recorded in
``field_status``. The validate stage must treat that as a recorded status (WARN), not a hard error;
an empty field *without* a recorded failure stays a hard structural violation; and the addon bundle
omits the failed section entirely instead of rendering placeholder text.
"""

from __future__ import annotations

from pipeline.addon.build_bundle import _omit_failed_prose_fields
from pipeline.validate.engine import validate_payload
from pipeline.validate.types import ValidationSeverity
from tests.factories.wiki_first_pages import (
    minimal_instance_page_payload,
    minimal_zone_page_payload,
)


def _issue_codes(report, *, path: str | None = None) -> list[str]:
    return [
        issue.code
        for issue in report.issues
        if path is None or issue.path == path
    ]


def _fail_zone_field(payload: dict, field: str, status: str = "synthesis_failed") -> dict:
    payload[field] = None
    payload.setdefault("field_status", {})[field] = status
    payload["provenance"][field] = []
    return payload


def test_zone_page_null_field_with_recorded_failure_is_warn_not_hard_fail() -> None:
    payload = _fail_zone_field(minimal_zone_page_payload(), "at_a_glance")

    report = validate_payload("zone_page", payload)

    at_glance_issues = [issue for issue in report.issues if issue.path == "$.at_a_glance"]
    assert at_glance_issues, "recorded failure should still surface as an issue"
    assert all(
        issue.severity == ValidationSeverity.WARN and issue.code == "structure.section_synthesis_failed"
        for issue in at_glance_issues
    )
    # No schema/budget/provenance hard-fail may leak from the null field.
    assert not any(
        issue.severity == ValidationSeverity.HARD_FAIL and "at_a_glance" in issue.path
        for issue in report.issues
    )


def test_zone_page_null_currently_no_evidence_is_warn() -> None:
    payload = _fail_zone_field(minimal_zone_page_payload(), "currently", status="no_evidence")

    report = validate_payload("zone_page", payload)

    currently_issues = [issue for issue in report.issues if issue.path == "$.currently"]
    assert currently_issues
    assert all(issue.severity == ValidationSeverity.WARN for issue in currently_issues)


def test_zone_page_null_field_without_recorded_status_stays_hard_fail() -> None:
    payload = minimal_zone_page_payload()
    payload["at_a_glance"] = None
    payload["provenance"]["at_a_glance"] = []
    # No field_status entry: the null is unexplained, so the structural contract still hard-fails.

    report = validate_payload("zone_page", payload)

    assert any(
        issue.code == "structure.required_section_empty"
        and issue.path == "$.at_a_glance"
        and issue.severity == ValidationSeverity.HARD_FAIL
        for issue in report.issues
    )


def test_instance_page_null_overview_with_recorded_failure_is_warn() -> None:
    payload = minimal_instance_page_payload()
    payload["overview"] = None
    payload["field_status"] = {"overview": "synthesis_failed"}
    payload["provenance"]["story_context"] = []

    report = validate_payload("instance_page", payload)

    overview_issues = [issue for issue in report.issues if issue.path == "$.overview"]
    assert overview_issues
    assert all(
        issue.severity == ValidationSeverity.WARN and issue.code == "structure.section_synthesis_failed"
        for issue in overview_issues
    )
    assert not any(
        issue.severity == ValidationSeverity.HARD_FAIL and issue.path == "$.overview"
        for issue in report.issues
    )


def test_bundle_omits_null_prose_fields_and_keeps_field_status() -> None:
    payload = _fail_zone_field(minimal_zone_page_payload(), "at_a_glance")

    out = _omit_failed_prose_fields(payload)

    assert "at_a_glance" not in out  # failed section omitted: no placeholder text
    assert out["currently"] == payload["currently"]  # healthy fields untouched
    assert out["field_status"]["at_a_glance"] == "synthesis_failed"  # audit trail kept


def test_bundle_keeps_non_null_prose_fields() -> None:
    payload = minimal_zone_page_payload()

    out = _omit_failed_prose_fields(payload)

    assert out["at_a_glance"] == payload["at_a_glance"]
    assert out["currently"] == payload["currently"]
