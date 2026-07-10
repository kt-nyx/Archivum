from __future__ import annotations

from scripts.questline_quality_report import evaluate_run


def test_quality_report_handles_missing_zone_draft(tmp_path) -> None:
    assert evaluate_run(tmp_path) == []
