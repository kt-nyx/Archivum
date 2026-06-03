#!/usr/bin/env python3
"""Instance-page quality rubric for a pipeline run (Slice I6).

Aggregates the deterministic instance acceptance signals into a per-instance scorecard so a
pilot run's instance quality can be reviewed, archived, and gated objectively:

- Release-gate validation (``validate_payload`` with ``release_gate=True``, fact-check off):
  structural passthrough/boilerplate, budgets, provenance caps, empty key_characters.
- Prose detectors (``instance_lint``): at_a_glance / overview / key-character anchor + quality.
- Pool-aware key-character minimum (keyed off the decision sidecar roster when present).
- Role diversity (``assess_role_diversity`` against the sidecar roster).

The report is a pure function of the ``instance_page`` drafts plus the
``instance_key_character_decisions.json`` sidecar; it never touches the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.contracts.models import INSTANCE_MIN_KEY_CHARACTERS
from pipeline.generate.draft.instance_lint import (
    assess_role_diversity,
    is_generic_at_a_glance,
    is_generic_key_character_summary,
    is_generic_overview,
    lint_at_a_glance,
    lint_key_character_summary,
    lint_overview,
    lint_passthrough_fragment,
)
from pipeline.validate.context import (
    build_entity_validation_context,
    load_validation_run_resources,
)
from pipeline.validate.engine import validate_payload

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
_STATUS_RANK = {STATUS_PASS: 0, STATUS_WARN: 1, STATUS_FAIL: 2}


@dataclass
class Finding:
    """One rubric signal against an instance page."""

    severity: str  # "fail" | "warn"
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class InstanceScore:
    instance_id: str
    name: str
    status: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "name": self.name,
            "status": self.status,
            "fail_count": sum(1 for f in self.findings if f.severity == "fail"),
            "warn_count": sum(1 for f in self.findings if f.severity == "warn"),
            "findings": [f.to_dict() for f in self.findings],
        }


def _status_from_findings(findings: list[Finding]) -> str:
    if any(f.severity == "fail" for f in findings):
        return STATUS_FAIL
    if any(f.severity == "warn" for f in findings):
        return STATUS_WARN
    return STATUS_PASS


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_sidecar_roster(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Map instance_id -> ranked candidate roster from the decision sidecar."""
    roster_by_instance: dict[str, list[dict[str, Any]]] = {}
    blob = _load_json(run_root / "data" / "decisions" / "instance_key_character_decisions.json")
    if isinstance(blob, list):
        for row in blob:
            if not isinstance(row, dict):
                continue
            instance_id = str(row.get("instance_id", "")).strip()
            candidates = [c for c in row.get("candidates", []) if isinstance(c, dict)]
            if instance_id:
                roster_by_instance[instance_id] = candidates
    return roster_by_instance


def _gate_findings(payload: dict[str, Any], instance_id: str, run_root: Path) -> list[Finding]:
    resources = load_validation_run_resources(run_root)
    context = build_entity_validation_context(
        entity_id=instance_id,
        fact_check_profile="off",
        release_gate=True,
        resources=resources,
    )
    report = validate_payload("instance_page", payload, validation_context=context)
    findings: list[Finding] = []
    for issue in report.issues:
        severity = "fail" if issue.severity.value == "hard-fail" else "warn"
        findings.append(
            Finding(
                severity=severity,
                code=f"gate.{issue.code}",
                message=f"{issue.message} ({issue.path})",
            )
        )
    return findings


def _prose_findings(payload: dict[str, Any], instance_name: str) -> list[Finding]:
    findings: list[Finding] = []

    at_a_glance = str(payload.get("at_a_glance", "")).strip()
    if not at_a_glance:
        findings.append(Finding("fail", "semantics.at_a_glance_empty", "at_a_glance is empty"))
    else:
        if is_generic_at_a_glance(at_a_glance):
            findings.append(
                Finding("fail", "semantics.at_a_glance_generic", "at_a_glance reads like a stub")
            )
        for issue in lint_at_a_glance(at_a_glance, instance_name=instance_name):
            findings.append(Finding("fail", "semantics.at_a_glance_lint", issue))

    overview = str(payload.get("overview", "")).strip()
    if not overview:
        findings.append(Finding("fail", "semantics.overview_empty", "overview is empty"))
    else:
        if is_generic_overview(overview):
            findings.append(
                Finding("fail", "semantics.overview_generic", "overview reads like a stub")
            )
        for issue in lint_overview(overview, instance_name=instance_name):
            findings.append(Finding("fail", "semantics.overview_lint", issue))
        for issue in lint_passthrough_fragment(overview):
            findings.append(Finding("fail", "semantics.overview_passthrough", issue))

    for section in payload.get("history_sections") or []:
        if not isinstance(section, dict):
            continue
        body = str(section.get("body", "")).strip()
        for issue in lint_passthrough_fragment(body):
            findings.append(Finding("fail", "semantics.history_passthrough", issue))

    for card in payload.get("key_characters") or []:
        if not isinstance(card, dict):
            continue
        summary = str(card.get("summary", "")).strip()
        boss_name = str(card.get("name", "")).strip()
        if is_generic_key_character_summary(summary):
            findings.append(
                Finding(
                    "fail",
                    "semantics.key_character_generic",
                    f"key_character summary reads like a stub: {boss_name!r}",
                )
            )
        for issue in lint_key_character_summary(
            summary, boss_name=boss_name, instance_name=instance_name
        ):
            findings.append(
                Finding("fail", "semantics.key_character_lint", f"{boss_name!r}: {issue}")
            )

    return findings


def _roster_findings(
    payload: dict[str, Any], roster: list[dict[str, Any]] | None
) -> list[Finding]:
    findings: list[Finding] = []
    if roster is None:
        return findings
    key_characters = [c for c in payload.get("key_characters") or [] if isinstance(c, dict)]
    pool_size = len(roster)
    emitted = len(key_characters)
    if pool_size >= INSTANCE_MIN_KEY_CHARACTERS and emitted < INSTANCE_MIN_KEY_CHARACTERS:
        findings.append(
            Finding(
                "fail",
                "semantics.key_characters_below_minimum",
                f"emitted {emitted} key_characters below minimum "
                f"{INSTANCE_MIN_KEY_CHARACTERS} despite {pool_size} roster candidates",
            )
        )
    severity, reason = assess_role_diversity(key_characters, roster)
    if severity == "fail":
        findings.append(Finding("fail", "semantics.role_diversity", reason))
    elif severity == "warn":
        findings.append(Finding("warn", "semantics.role_diversity", reason))
    return findings


def evaluate_instance(
    payload: dict[str, Any],
    instance_id: str,
    run_root: Path,
    roster: list[dict[str, Any]] | None,
) -> InstanceScore:
    instance_name = str(payload.get("name", instance_id)).strip() or instance_id
    findings = _gate_findings(payload, instance_id, run_root)
    findings.extend(_prose_findings(payload, instance_name))
    findings.extend(_roster_findings(payload, roster))
    return InstanceScore(
        instance_id=instance_id,
        name=instance_name,
        status=_status_from_findings(findings),
        findings=findings,
    )


def evaluate_run(run_root: Path) -> list[InstanceScore]:
    draft_dir = run_root / "data" / "drafts" / "instance_page"
    if not draft_dir.exists():
        return []
    roster_by_instance = _load_sidecar_roster(run_root)
    scores: list[InstanceScore] = []
    for draft_path in sorted(draft_dir.glob("instance-*.json")):
        raw = _load_json(draft_path)
        instance_id = draft_path.stem
        if not isinstance(raw, dict):
            scores.append(
                InstanceScore(
                    instance_id=instance_id,
                    name=instance_id,
                    status=STATUS_FAIL,
                    findings=[Finding("fail", "rubric.not_json_object", "draft is not an object")],
                )
            )
            continue
        scores.append(
            evaluate_instance(raw, instance_id, run_root, roster_by_instance.get(instance_id))
        )
    return scores


def run_summary(scores: list[InstanceScore]) -> dict[str, Any]:
    counts = {STATUS_PASS: 0, STATUS_WARN: 0, STATUS_FAIL: 0}
    for score in scores:
        counts[score.status] += 1
    overall = STATUS_PASS
    for score in scores:
        if _STATUS_RANK[score.status] > _STATUS_RANK[overall]:
            overall = score.status
    return {
        "instance_count": len(scores),
        "overall_status": overall,
        "status_counts": counts,
        "instances": [score.to_dict() for score in scores],
    }


def render_markdown(summary: dict[str, Any], run_label: str) -> str:
    lines = [f"# Instance quality report - {run_label}", ""]
    counts = summary["status_counts"]
    lines.append(
        f"Overall: **{summary['overall_status']}** "
        f"({summary['instance_count']} instance(s); "
        f"{counts[STATUS_PASS]} PASS / {counts[STATUS_WARN]} WARN / {counts[STATUS_FAIL]} FAIL)"
    )
    lines.append("")
    for instance in summary["instances"]:
        lines.append(
            f"## {instance['instance_id']} - {instance['status']} "
            f"({instance['fail_count']} fail / {instance['warn_count']} warn)"
        )
        if not instance["findings"]:
            lines.append("- (no findings)")
        for finding in instance["findings"]:
            lines.append(
                f"- [{finding['severity'].upper()}] `{finding['code']}`: {finding['message']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_out_paths(run_root: Path, out: str | None) -> tuple[Path, Path]:
    if out is None:
        base = run_root / "reports" / "instance_quality_report"
    else:
        candidate = Path(out)
        # Strip a known report suffix so callers can pass either a stem or a .json/.md path.
        if candidate.suffix in {".json", ".md"}:
            base = candidate.with_suffix("")
        else:
            base = candidate
    return base.with_suffix(".json"), base.with_suffix(".md")


def write_reports(run_root: Path, summary: dict[str, Any], out: str | None) -> tuple[Path, Path]:
    json_path, md_path = _resolve_out_paths(run_root, out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary, run_root.name), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Instance-page quality rubric for a run root.")
    parser.add_argument("run_root", type=Path, help="Pipeline run root (artifacts/runs/<id>)")
    parser.add_argument(
        "--out",
        default=None,
        help="Report path stem or .json/.md (default: <run_root>/reports/instance_quality_report)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Treat WARN as a failing exit code (strict promotion gate).",
    )
    args = parser.parse_args(argv)

    run_root: Path = args.run_root
    if not run_root.exists():
        print(f"FAIL: run root not found: {run_root}", file=sys.stderr)
        return 2

    scores = evaluate_run(run_root)
    if not scores:
        print(f"PASS: no instance drafts under {run_root} (nothing to score)")
        return 0

    summary = run_summary(scores)
    json_path, md_path = write_reports(run_root, summary, args.out)
    counts = summary["status_counts"]
    print(
        f"instance quality: {summary['overall_status']} "
        f"({counts[STATUS_PASS]} PASS / {counts[STATUS_WARN]} WARN / {counts[STATUS_FAIL]} FAIL) "
        f"-> {json_path}"
    )
    for score in scores:
        if score.status != STATUS_PASS:
            print(f"  {score.status}: {score.instance_id}")

    has_fail = counts[STATUS_FAIL] > 0
    has_warn = counts[STATUS_WARN] > 0
    if has_fail or (args.gate and has_warn):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
