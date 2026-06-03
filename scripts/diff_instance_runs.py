#!/usr/bin/env python3
"""Before/after instance-page diff for two pipeline runs (Slice I6).

Compares the ``instance_page`` drafts (and the key-character decision sidecar) between a
baseline and a candidate run root, then writes an archivable JSON + Markdown report with an
auto-generated rationale line per changed instance. An optional ``--notes`` file lets an
operator attach manual promotion rationale to the archived diff.

Deterministic and offline: it only reads run artifacts on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _word_count(text: str) -> int:
    return len(str(text).split())


def _load_instances(run_root: Path) -> dict[str, dict[str, Any]]:
    draft_dir = run_root / "data" / "drafts" / "instance_page"
    pages: dict[str, dict[str, Any]] = {}
    if not draft_dir.exists():
        return pages
    for draft_path in sorted(draft_dir.glob("instance-*.json")):
        raw = _load_json(draft_path)
        if isinstance(raw, dict):
            pages[draft_path.stem] = raw
    return pages


def _load_sidecar(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    roster: dict[str, list[dict[str, Any]]] = {}
    blob = _load_json(run_root / "data" / "decisions" / "instance_key_character_decisions.json")
    if isinstance(blob, list):
        for row in blob:
            if not isinstance(row, dict):
                continue
            instance_id = str(row.get("instance_id", "")).strip()
            if instance_id:
                roster[instance_id] = [c for c in row.get("candidates", []) if isinstance(c, dict)]
    return roster


def _character_role_map(page: dict[str, Any]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for card in page.get("key_characters") or []:
        if not isinstance(card, dict):
            continue
        name = str(card.get("name", "")).strip()
        if name:
            roles[name] = str(card.get("role", "")).strip() or "uncertain"
    return roles


def _provenance_counts(page: dict[str, Any]) -> dict[str, int]:
    provenance = page.get("provenance") or {}
    counts: dict[str, int] = {}
    for key in ("identity_header", "story_context"):
        value = provenance.get(key)
        counts[key] = len(value) if isinstance(value, list) else 0
    for key in ("key_characters", "major_factions"):
        value = provenance.get(key)
        counts[key] = len(value) if isinstance(value, dict) else 0
    return counts


def _emitted_roster_names(candidates: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for candidate in candidates:
        if candidate.get("emitted"):
            name = str(candidate.get("name", "")).strip()
            if name:
                names.add(name)
    return names


def diff_instance(
    instance_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    before_roster: list[dict[str, Any]] | None,
    after_roster: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if before is None:
        return {"instance_id": instance_id, "change": "added", "rationale": "new instance page"}
    if after is None:
        return {"instance_id": instance_id, "change": "removed", "rationale": "instance dropped"}

    fields: dict[str, Any] = {}

    before_aag = str(before.get("at_a_glance", "")).strip()
    after_aag = str(after.get("at_a_glance", "")).strip()
    if before_aag != after_aag:
        fields["at_a_glance"] = {"changed": True, "before": before_aag, "after": after_aag}

    before_ov = str(before.get("overview", "")).strip()
    after_ov = str(after.get("overview", "")).strip()
    if before_ov != after_ov:
        fields["overview"] = {
            "changed": True,
            "word_delta": _word_count(after_ov) - _word_count(before_ov),
        }

    before_hist = len(before.get("history_sections") or [])
    after_hist = len(after.get("history_sections") or [])
    if before_hist != after_hist:
        fields["history_sections_count"] = {"before": before_hist, "after": after_hist}

    before_roles = _character_role_map(before)
    after_roles = _character_role_map(after)
    added = sorted(set(after_roles) - set(before_roles))
    removed = sorted(set(before_roles) - set(after_roles))
    role_changes = sorted(
        f"{name}: {before_roles[name]} -> {after_roles[name]}"
        for name in set(before_roles) & set(after_roles)
        if before_roles[name] != after_roles[name]
    )
    if added or removed or role_changes:
        fields["key_characters"] = {
            "added": added,
            "removed": removed,
            "role_changes": role_changes,
        }

    before_source = str(before.get("lore_source", "")).strip()
    after_source = str(after.get("lore_source", "")).strip()
    if before_source != after_source:
        fields["lore_source"] = {"before": before_source, "after": after_source}

    before_counts = _provenance_counts(before)
    after_counts = _provenance_counts(after)
    prov_delta = {
        key: {"before": before_counts[key], "after": after_counts[key]}
        for key in before_counts
        if before_counts[key] != after_counts[key]
    }
    if prov_delta:
        fields["provenance_counts"] = prov_delta

    if before_roster is not None or after_roster is not None:
        before_names = _emitted_roster_names(before_roster or [])
        after_names = _emitted_roster_names(after_roster or [])
        if before_names != after_names or len(before_roster or []) != len(after_roster or []):
            fields["decision_sidecar"] = {
                "roster_size": {
                    "before": len(before_roster or []),
                    "after": len(after_roster or []),
                },
                "emitted_added": sorted(after_names - before_names),
                "emitted_removed": sorted(before_names - after_names),
            }

    change = "changed" if fields else "unchanged"
    return {
        "instance_id": instance_id,
        "change": change,
        "fields": fields,
        "rationale": _auto_rationale(change, fields),
    }


def _auto_rationale(change: str, fields: dict[str, Any]) -> str:
    if change == "unchanged":
        return "no instance-page changes detected"
    parts: list[str] = []
    if "overview" in fields:
        parts.append(f"overview reworded ({fields['overview']['word_delta']:+d} words)")
    if "at_a_glance" in fields:
        parts.append("at_a_glance reworded")
    if "history_sections_count" in fields:
        delta = fields["history_sections_count"]
        parts.append(f"history sections {delta['before']} -> {delta['after']}")
    if "key_characters" in fields:
        kc = fields["key_characters"]
        if kc["added"]:
            parts.append(f"cast +{len(kc['added'])} ({', '.join(kc['added'])})")
        if kc["removed"]:
            parts.append(f"cast -{len(kc['removed'])} ({', '.join(kc['removed'])})")
        if kc["role_changes"]:
            parts.append(f"role changes: {'; '.join(kc['role_changes'])}")
    if "lore_source" in fields:
        ls = fields["lore_source"]
        parts.append(f"lore_source {ls['before']} -> {ls['after']}")
    if "provenance_counts" in fields:
        parts.append("provenance pointer counts changed")
    if "decision_sidecar" in fields:
        parts.append("key-character roster changed")
    return "; ".join(parts) if parts else "metadata changed"


def diff_runs(baseline: Path, candidate: Path) -> dict[str, Any]:
    before_pages = _load_instances(baseline)
    after_pages = _load_instances(candidate)
    before_rosters = _load_sidecar(baseline)
    after_rosters = _load_sidecar(candidate)

    instance_ids = sorted(set(before_pages) | set(after_pages))
    instances = [
        diff_instance(
            instance_id,
            before_pages.get(instance_id),
            after_pages.get(instance_id),
            before_rosters.get(instance_id),
            after_rosters.get(instance_id),
        )
        for instance_id in instance_ids
    ]
    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for instance in instances:
        counts[instance["change"]] += 1
    return {
        "baseline": baseline.name,
        "candidate": candidate.name,
        "instance_count": len(instance_ids),
        "change_counts": counts,
        "instances": instances,
    }


def render_markdown(report: dict[str, Any], notes: str | None) -> str:
    lines = [
        f"# Instance run diff - {report['baseline']} -> {report['candidate']}",
        "",
        (
            f"{report['instance_count']} instance(s): "
            f"{report['change_counts']['added']} added / "
            f"{report['change_counts']['removed']} removed / "
            f"{report['change_counts']['changed']} changed / "
            f"{report['change_counts']['unchanged']} unchanged"
        ),
        "",
    ]
    for instance in report["instances"]:
        lines.append(f"## {instance['instance_id']} - {instance['change']}")
        lines.append(f"- rationale: {instance['rationale']}")
        lines.append("")
    if notes:
        lines.append("## Operator notes")
        lines.append("")
        lines.append(notes.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_out_paths(candidate: Path, out: str | None) -> tuple[Path, Path]:
    if out is None:
        base = candidate / "reports" / "instance_run_diff"
    else:
        path = Path(out)
        base = path.with_suffix("") if path.suffix in {".json", ".md"} else path
    return base.with_suffix(".json"), base.with_suffix(".md")


def write_reports(
    candidate: Path, report: dict[str, Any], out: str | None, notes: str | None
) -> tuple[Path, Path]:
    json_path, md_path = _resolve_out_paths(candidate, out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(report)
    if notes:
        payload["operator_notes"] = notes.strip()
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report, notes), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff instance pages between two run roots.")
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline run root")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate run root")
    parser.add_argument(
        "--out",
        default=None,
        help="Report path stem or .json/.md (default: <candidate>/reports/instance_run_diff)",
    )
    parser.add_argument(
        "--notes",
        type=Path,
        default=None,
        help="Optional text file of operator rationale to embed in the archived diff.",
    )
    args = parser.parse_args(argv)

    for label, root in (("baseline", args.baseline), ("candidate", args.candidate)):
        if not root.exists():
            print(f"FAIL: {label} run root not found: {root}", file=sys.stderr)
            return 2

    notes = None
    if args.notes is not None:
        if not args.notes.exists():
            print(f"FAIL: notes file not found: {args.notes}", file=sys.stderr)
            return 2
        notes = args.notes.read_text(encoding="utf-8")

    report = diff_runs(args.baseline, args.candidate)
    json_path, md_path = write_reports(args.candidate, report, args.out, notes)
    counts = report["change_counts"]
    print(
        f"instance diff {report['baseline']} -> {report['candidate']}: "
        f"{counts['added']} added / {counts['removed']} removed / "
        f"{counts['changed']} changed / {counts['unchanged']} unchanged -> {json_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
