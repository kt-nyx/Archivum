"""Slice 7: citation shortfall as a soft retry reason, never a fabricated pointer."""

from __future__ import annotations

from typing import Any

from pipeline.contracts.models import required_pointer_count
from pipeline.generate.draft.pages.assembly import (
    CITATION_REASON_PREFIX,
    citation_shortfall_reasons,
)
from pipeline.generate.draft.prose_synthesis import synthesize_with_validation
from pipeline.validate.engine import validate_payload
from pipeline.validate.types import ValidationSeverity
from tests.factories.wiki_first_pages import minimal_zone_page_payload

_POOL = [
    {"snippet": "First paragraph.", "source_id": "src-a", "canonical_evidence_id": "canonical-1"},
    {"snippet": "Second paragraph.", "source_id": "src-a", "canonical_evidence_id": "canonical-2"},
    {"snippet": "Third paragraph.", "source_id": "src-a", "canonical_evidence_id": "canonical-3"},
]

_LONG_TEXT = " ".join(["word"] * 200)  # 200 words -> 2 pointers recommended


def test_citation_shortfall_fires_below_required_count() -> None:
    reasons = citation_shortfall_reasons(
        text=_LONG_TEXT, used_ids=["canonical-1"], pool=_POOL
    )
    assert len(reasons) == 1
    assert reasons[0].startswith(CITATION_REASON_PREFIX)
    assert "at least 2" in reasons[0]


def test_citation_shortfall_satisfied_and_unresolvable_ids_do_not_count() -> None:
    # Two resolvable citations satisfy a 200-word text; hallucinated ids never count.
    assert (
        citation_shortfall_reasons(
            text=_LONG_TEXT,
            used_ids=["canonical-1", "canonical-2", "made-up"],
            pool=_POOL,
        )
        == []
    )
    reasons = citation_shortfall_reasons(
        text=_LONG_TEXT, used_ids=["made-up", "also-fake"], pool=_POOL
    )
    assert reasons and "only 0 distinct" in reasons[0]


def test_citation_shortfall_required_capped_by_pool_size() -> None:
    # A one-paragraph pool can never satisfy "cite 2", so the requirement caps at 1 and the
    # reason stays satisfiable.
    pool = _POOL[:1]
    assert required_pointer_count(200) == 2
    assert (
        citation_shortfall_reasons(text=_LONG_TEXT, used_ids=["canonical-1"], pool=pool) == []
    )


def test_citation_shortfall_empty_text_is_silent() -> None:
    assert citation_shortfall_reasons(text="  ", used_ids=[], pool=_POOL) == []


def test_driver_soft_reason_retries_then_ships_with_shortfall_recorded() -> None:
    """A hard-clean but under-cited attempt retries with the citation reason in the feedback,
    and on exhaustion ships (ok=True) carrying the outstanding soft reasons — the field is never
    nulled and nothing is fabricated."""
    feedbacks: list[str] = []

    def _call(reinforce: str) -> dict[str, Any]:
        feedbacks.append(reinforce)
        return {"text": "A fine summary.", "used": []}

    result = synthesize_with_validation(
        call=_call,
        extract_bodies=lambda payload: [str(payload.get("text", ""))],
        validate_soft=lambda payload: citation_shortfall_reasons(
            text=str(payload.get("text", "")),
            used_ids=list(payload.get("used", [])),
            pool=_POOL,
        ),
        label="test_soft",
        max_attempts=2,
    )
    assert result.ok is True
    assert result.reasons == []
    assert result.soft_reasons and result.soft_reasons[0].startswith(CITATION_REASON_PREFIX)
    assert len(feedbacks) == 2
    assert CITATION_REASON_PREFIX in feedbacks[1]


def test_driver_soft_reason_clean_second_attempt_ends_loop() -> None:
    calls: list[int] = []

    def _call(reinforce: str) -> dict[str, Any]:
        calls.append(1)
        if len(calls) == 1:
            return {"text": _LONG_TEXT, "used": []}
        return {"text": _LONG_TEXT, "used": ["canonical-1", "canonical-2"]}

    result = synthesize_with_validation(
        call=_call,
        extract_bodies=lambda payload: [str(payload.get("text", ""))],
        validate_soft=lambda payload: citation_shortfall_reasons(
            text=str(payload.get("text", "")),
            used_ids=list(payload.get("used", [])),
            pool=_POOL,
        ),
        label="test_soft_clean",
        max_attempts=3,
    )
    assert result.ok is True
    assert result.soft_reasons == []
    assert len(calls) == 2


def test_validate_pointer_shortfall_is_warn_not_hard_fail() -> None:
    """A real-but-short pointer list WARNs (pointers are never fabricated); an empty list on a
    non-empty section still hard-fails."""
    payload = minimal_zone_page_payload()
    # History text over 120 words -> 2 pointers recommended, only 1 present.
    payload["history_sections"] = [
        {
            "heading": "Long Era",
            "body": " ".join(["conflict"] * 130),
            "source_refs": [],
        }
    ]
    report = validate_payload("zone_page", payload)
    shortfalls = [
        issue for issue in report.issues if issue.code == "provenance.pointer_count_shortfall"
    ]
    assert shortfalls and all(
        issue.severity == ValidationSeverity.WARN for issue in shortfalls
    )
    assert not any(
        issue.code == "provenance.missing_section_pointers" and "history" in issue.path
        for issue in report.issues
    )

    payload["provenance"]["history"] = []
    report = validate_payload("zone_page", payload)
    assert any(
        issue.code == "provenance.missing_section_pointers"
        and "history" in issue.path
        and issue.severity == ValidationSeverity.HARD_FAIL
        for issue in report.issues
    )
