#!/usr/bin/env python3
"""Before/after zone questline diff for two pipeline runs (Slice E)."""

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


def _load_zone_draft(run_root: Path, zone_id: str) -> dict[str, Any] | None:
    path = run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json"
    raw = _load_json(path)
    return raw if isinstance(raw, dict) else None


def _card_snapshot(card: dict[str, Any]) -> dict[str, Any]:
    chain_refs = card.get("chain_refs", [])
    return {
        "id": str(card.get("id", "")),
        "title": str(card.get("title", "")),
        "faction": str(card.get("faction", "")),
        "start_anchor": str(card.get("start_anchor", "")),
        "chain_refs_count": len(chain_refs) if isinstance(chain_refs, list) else 0,
        "cta_hook_words": _word_count(str(card.get("cta_hook", ""))),
    }


def _diff_cards(
    baseline_cards: list[dict[str, Any]],
    candidate_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_by_id = {
        str(card.get("id", "")): _card_snapshot(card)
        for card in baseline_cards
        if isinstance(card, dict) and card.get("id")
    }
    candidate_by_id = {
        str(card.get("id", "")): _card_snapshot(card)
        for card in candidate_cards
        if isinstance(card, dict) and card.get("id")
    }
    changes: list[dict[str, Any]] = []
    for card_id in sorted(set(baseline_by_id) | set(candidate_by_id)):
        before = baseline_by_id.get(card_id)
        after = candidate_by_id.get(card_id)
        if before == after:
            continue
        changes.append({"card_id": card_id, "baseline": before, "candidate": after})
    return changes


def build_diff(
    *,
    baseline_root: Path,
    candidate_root: Path,
    zone_id: str,
    notes: str,
) -> dict[str, Any]:
    baseline_draft = _load_zone_draft(baseline_root, zone_id) or {}
    candidate_draft = _load_zone_draft(candidate_root, zone_id) or {}
    baseline_cards = [
        row for row in baseline_draft.get("major_questlines", []) if isinstance(row, dict)
    ]
    candidate_cards = [
        row for row in candidate_draft.get("major_questlines", []) if isinstance(row, dict)
    ]
    return {
        "zone_id": zone_id,
        "baseline_run": baseline_root.name,
        "candidate_run": candidate_root.name,
        "notes": notes.strip(),
        "card_changes": _diff_cards(baseline_cards, candidate_cards),
        "baseline_card_count": len(baseline_cards),
        "candidate_card_count": len(candidate_cards),
        "rankings_changed": _load_json(
            baseline_root / "data" / "discovery" / "zone_quest_cluster_rankings.json"
        )
        != _load_json(candidate_root / "data" / "discovery" / "zone_quest_cluster_rankings.json"),
        "metadata_changed": _load_json(
            baseline_root / "data" / "discovery" / "zone_questline_card_metadata.json"
        )
        != _load_json(candidate_root / "data" / "discovery" / "zone_questline_card_metadata.json"),
    }


def render_markdown(diff: dict[str, Any]) -> str:
    lines = [
        f"# Zone questline diff - {diff['zone_id']}",
        "",
        f"Baseline: `{diff['baseline_run']}` → Candidate: `{diff['candidate_run']}`",
        f"Cards: {diff['baseline_card_count']} → {diff['candidate_card_count']}",
        f"Rankings changed: {diff['rankings_changed']}",
        f"Metadata changed: {diff['metadata_changed']}",
        "",
    ]
    if diff.get("notes"):
        lines.extend(["## Notes", "", diff["notes"], ""])
    lines.append("## Card changes")
    if not diff["card_changes"]:
        lines.append("- (no card field changes)")
    else:
        for change in diff["card_changes"]:
            lines.append(f"- `{change['card_id']}`")
            lines.append(f"  - baseline: {change['baseline']}")
            lines.append(f"  - candidate: {change['candidate']}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff zone questline cards between two runs.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--zone-id", default="zone-western-plaguelands")
    parser.add_argument("--out", default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--notes-file", default=None)
    args = parser.parse_args(argv)
    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    diff = build_diff(
        baseline_root=args.baseline,
        candidate_root=args.candidate,
        zone_id=args.zone_id,
        notes=notes,
    )
    if args.out:
        base = Path(args.out)
        if base.suffix in {".json", ".md"}:
            json_path = base.with_suffix(".json")
            md_path = base.with_suffix(".md")
        else:
            json_path = base.with_suffix(".json")
            md_path = base.with_suffix(".md")
    else:
        json_path = args.candidate / "reports" / "zone_questline_diff.json"
        md_path = args.candidate / "reports" / "zone_questline_diff.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(diff, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(diff), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
