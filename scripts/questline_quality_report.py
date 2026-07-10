#!/usr/bin/env python3
"""Questline-card quality rubric for a pipeline run (Slice E)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.discovery.questline_promotion_gate import (
    QuestlineRunArtifacts,
    check_questline_promotion,
    load_questline_run_artifacts,
    warn_questline_promotion,
)
from pipeline.validate.context import build_entity_validation_context, load_validation_run_resources
from pipeline.validate.engine import validate_payload

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
_STATUS_RANK = {STATUS_PASS: 0, STATUS_WARN: 1, STATUS_FAIL: 2}


@dataclass
class Finding:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class ZoneQuestlineScore:
    zone_id: str
    name: str
    status: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "status": self.status,
            "fail_count": sum(1 for item in self.findings if item.severity == "fail"),
            "warn_count": sum(1 for item in self.findings if item.severity == "warn"),
            "findings": [item.to_dict() for item in self.findings],
        }


def _status_from_findings(findings: list[Finding]) -> str:
    if any(item.severity == "fail" for item in findings):
        return STATUS_FAIL
    if any(item.severity == "warn" for item in findings):
        return STATUS_WARN
    return STATUS_PASS


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _covered_cluster_ids(run_root: Path, zone_id: str) -> set[str]:
    covered: set[str] = set()
    evidence_path = run_root / "data" / "evidence" / "evidence_packs.jsonl"
    if not evidence_path.exists():
        return covered
    for line in evidence_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("field_name", "")) != "quest_cluster_lore":
            continue
        build_meta = row.get("build_meta") or {}
        subject_zone = str(build_meta.get("subject_zone_id", row.get("subject_id", ""))).strip()
        if subject_zone not in {"", zone_id}:
            continue
        cluster_id = str(build_meta.get("cluster_id", "")).strip()
        if cluster_id:
            covered.add(cluster_id)
    return covered


def evaluate_zone(
    run_root: Path,
    zone_id: str,
) -> ZoneQuestlineScore:
    draft_path = run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json"
    raw = _load_json(draft_path)
    if not isinstance(raw, dict):
        return ZoneQuestlineScore(
            zone_id=zone_id,
            name=zone_id,
            status=STATUS_FAIL,
            findings=[Finding("fail", "rubric.missing_draft", f"missing draft at {draft_path}")],
        )

    zone_name = str(raw.get("name", zone_id)).strip() or zone_id
    findings: list[Finding] = []

    resources = load_validation_run_resources(run_root)
    report = validate_payload(
        "zone_page",
        raw,
        validation_context=build_entity_validation_context(
            entity_id=zone_id,
            fact_check_profile="off",
            release_gate=True,
            resources=resources,
        ),
    )
    for issue in report.issues:
        severity = "fail" if issue.severity.value == "hard-fail" else "warn"
        findings.append(
            Finding(
                severity=severity,
                code=f"gate.{issue.code}",
                message=f"{issue.message} ({issue.path})",
            )
        )

    artifacts = load_questline_run_artifacts(run_root, zone_id)
    artifacts = QuestlineRunArtifacts(
        zone_id=artifacts.zone_id,
        cards=[row for row in raw.get("major_questlines", []) if isinstance(row, dict)],
        included_cluster_ids=artifacts.included_cluster_ids,
        metadata_by_cluster=artifacts.metadata_by_cluster,
        card_id_to_cluster_id=artifacts.card_id_to_cluster_id,
        excluded_cluster_ids=artifacts.excluded_cluster_ids,
        v3_quest_rows=artifacts.v3_quest_rows,
    )
    for error in check_questline_promotion(
        artifacts,
        require_rankings=bool(artifacts.included_cluster_ids),
        require_evidence_coverage=bool(artifacts.included_cluster_ids),
        covered_cluster_ids=_covered_cluster_ids(run_root, zone_id),
    ):
        findings.append(Finding("fail", "semantics.questline_promotion", error))
    for warning in warn_questline_promotion(artifacts):
        findings.append(Finding("warn", "semantics.questline_promotion", warning))

    return ZoneQuestlineScore(
        zone_id=zone_id,
        name=zone_name,
        status=_status_from_findings(findings),
        findings=findings,
    )


def evaluate_run(
    run_root: Path,
    *,
    zone_id: str | None = None,
) -> list[ZoneQuestlineScore]:
    draft_dir = run_root / "data" / "drafts" / "zone_page"
    if not draft_dir.exists():
        return []
    if zone_id:
        targets = [zone_id]
    else:
        targets = sorted(path.stem for path in draft_dir.glob("zone-*.json"))
    return [
        evaluate_zone(run_root, target)
        for target in targets
    ]


def run_summary(scores: list[ZoneQuestlineScore]) -> dict[str, Any]:
    counts = {STATUS_PASS: 0, STATUS_WARN: 0, STATUS_FAIL: 0}
    for score in scores:
        counts[score.status] += 1
    overall = STATUS_PASS
    for score in scores:
        if _STATUS_RANK[score.status] > _STATUS_RANK[overall]:
            overall = score.status
    return {
        "zone_count": len(scores),
        "overall_status": overall,
        "status_counts": counts,
        "zones": [score.to_dict() for score in scores],
    }


def render_markdown(summary: dict[str, Any], run_label: str) -> str:
    lines = [f"# Questline quality report - {run_label}", ""]
    counts = summary["status_counts"]
    lines.append(
        f"Overall: **{summary['overall_status']}** "
        f"({summary['zone_count']} zone(s); "
        f"{counts[STATUS_PASS]} PASS / {counts[STATUS_WARN]} WARN / {counts[STATUS_FAIL]} FAIL)"
    )
    lines.append("")
    for zone in summary["zones"]:
        lines.append(
            f"## {zone['zone_id']} - {zone['status']} "
            f"({zone['fail_count']} fail / {zone['warn_count']} warn)"
        )
        if not zone["findings"]:
            lines.append("- (no findings)")
        for finding in zone["findings"]:
            lines.append(
                f"- [{finding['severity'].upper()}] `{finding['code']}`: {finding['message']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_reports(run_root: Path, summary: dict[str, Any], out: str | None) -> tuple[Path, Path]:
    if out is None:
        base = run_root / "reports" / "questline_quality_report"
    else:
        candidate = Path(out)
        base = candidate.with_suffix("") if candidate.suffix in {".json", ".md"} else candidate
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary, run_root.name), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Questline quality report for a pipeline run.")
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--zone-id", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--gate", action="store_true", help="Treat WARN as failure (exit 1).")
    args = parser.parse_args(argv)
    scores = evaluate_run(
        args.run_root,
        zone_id=args.zone_id,
    )
    summary = run_summary(scores)
    json_path, md_path = write_reports(args.run_root, summary, args.out)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Overall: {summary['overall_status']}")
    if summary["overall_status"] == STATUS_FAIL:
        return 1
    if args.gate and summary["overall_status"] == STATUS_WARN:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
