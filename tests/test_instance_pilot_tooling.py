"""Offline smoke tests for the Slice I6 pilot tooling.

Builds two synthetic run trees (a degraded baseline and the gold-quality candidate) entirely
from committed fixtures, then exercises both pilot scripts without any network or OpenAI:

- scripts/instance_quality_report.py must score the candidate PASS and the baseline FAIL.
- scripts/diff_instance_runs.py must report the overview rewrite + cast/role deltas.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.diff_instance_runs import diff_runs
from scripts.diff_instance_runs import main as diff_main
from scripts.instance_quality_report import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_WARN,
    evaluate_run,
)
from scripts.instance_quality_report import main as rubric_main

PILOT_DIR = Path("tests/fixtures/pilot")
GOLD_PATH = PILOT_DIR / "instance_page_scholomance_gold.json"
DECISIONS_PATH = PILOT_DIR / "instance_key_character_decisions_scholomance_gold.json"
_INSTANCE_FILE = "instance-scholomance.json"


def _gold_page() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def _gold_sidecar() -> list[dict]:
    return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))


def _write_run(root: Path, page: dict, sidecar: list[dict] | None) -> None:
    drafts = root / "data" / "drafts" / "instance_page"
    drafts.mkdir(parents=True, exist_ok=True)
    (drafts / _INSTANCE_FILE).write_text(json.dumps(page), encoding="utf-8")
    if sidecar is not None:
        decisions = root / "data" / "decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        (decisions / "instance_key_character_decisions.json").write_text(
            json.dumps(sidecar), encoding="utf-8"
        )


def _degraded_page() -> dict:
    page = _gold_page()
    # Passthrough fragment: lowercase mid-sentence start, no terminal punctuation.
    page["overview"] = (
        "scholomance was raised within the crypts beneath Caer Darrow as a hidden academy"
    )
    # Drop the cast to a single enemy so the pool-aware minimum and role diversity trip.
    page["key_characters"] = page["key_characters"][:1]
    return page


def _degraded_sidecar() -> list[dict]:
    sidecar = _gold_sidecar()
    candidates = sidecar[0]["candidates"]
    # Only Gandling stays emitted; an in-window ally is now documented but dropped.
    for candidate in candidates:
        candidate["emitted"] = candidate["name"] == "Darkmaster Gandling"
    candidates.insert(
        1,
        {
            "name": "Eris Havenfire",
            "role": "ally",
            "emitted": False,
            "merge_rank": None,
            "selection_reason": None,
        },
    )
    for rank, candidate in enumerate(
        (c for c in candidates if c.get("emitted")), start=1
    ):
        candidate["merge_rank"] = rank
        candidate.setdefault("selection_reason", "must_include_floor")
    return sidecar


def test_rubric_scores_candidate_pass_and_baseline_fail(tmp_path: Path) -> None:
    candidate_root = tmp_path / "run-candidate"
    baseline_root = tmp_path / "run-baseline"
    _write_run(candidate_root, _gold_page(), _gold_sidecar())
    _write_run(baseline_root, _degraded_page(), _degraded_sidecar())

    candidate_scores = evaluate_run(candidate_root)
    assert len(candidate_scores) == 1
    assert candidate_scores[0].status == STATUS_PASS

    baseline_scores = evaluate_run(baseline_root)
    assert len(baseline_scores) == 1
    assert baseline_scores[0].status == STATUS_FAIL
    codes = {f.code for f in baseline_scores[0].findings}
    assert "gate.structure.instance_page_overview_passthrough" in codes
    assert "semantics.role_diversity" in codes
    assert "semantics.key_characters_below_minimum" in codes


def test_rubric_main_exit_codes_and_report_files(tmp_path: Path) -> None:
    candidate_root = tmp_path / "run-candidate"
    baseline_root = tmp_path / "run-baseline"
    _write_run(candidate_root, _gold_page(), _gold_sidecar())
    _write_run(baseline_root, _degraded_page(), _degraded_sidecar())

    assert rubric_main([str(candidate_root)]) == 0
    assert rubric_main([str(baseline_root)]) == 1

    report_json = candidate_root / "reports" / "instance_quality_report.json"
    report_md = candidate_root / "reports" / "instance_quality_report.md"
    assert report_json.exists()
    assert report_md.exists()
    summary = json.loads(report_json.read_text(encoding="utf-8"))
    assert summary["overall_status"] == STATUS_PASS


def test_rubric_report_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "run-candidate"
    _write_run(root, _gold_page(), _gold_sidecar())
    rubric_main([str(root), "--out", str(tmp_path / "first")])
    rubric_main([str(root), "--out", str(tmp_path / "second")])
    first = (tmp_path / "first.json").read_text(encoding="utf-8")
    second = (tmp_path / "second.json").read_text(encoding="utf-8")
    assert first == second


def test_rubric_gate_flag_escalates_warn(tmp_path: Path) -> None:
    root = tmp_path / "run-warn"
    page = _gold_page()
    # All-enemy emitted cast; ally signal only outside the top-10 roster window.
    page["key_characters"] = [
        card for card in page["key_characters"] if card.get("role") == "enemy"
    ][:4]
    candidates: list[dict] = [
        {
            "name": card["name"],
            "role": "enemy",
            "emitted": True,
            "merge_rank": index,
            "selection_reason": "must_include_floor",
        }
        for index, card in enumerate(page["key_characters"], start=1)
    ]
    candidates.extend(
        {
            "name": f"Filler Enemy {index}",
            "role": "enemy",
            "emitted": False,
            "merge_rank": None,
            "selection_reason": None,
        }
        for index in range(6)
    )
    candidates.append(
        {
            "name": "Distant Ally",
            "role": "ally",
            "emitted": False,
            "merge_rank": None,
            "selection_reason": None,
        }
    )
    sidecar = [{"instance_id": "instance-scholomance", "candidates": candidates}]
    _write_run(root, page, sidecar)

    scores = evaluate_run(root)
    role_finding = next(
        f for f in scores[0].findings if f.code == "semantics.role_diversity"
    )
    assert role_finding.severity == "warn"
    assert scores[0].status == STATUS_WARN
    assert rubric_main([str(root)]) == 0
    assert rubric_main([str(root), "--gate"]) == 1


def test_rubric_catches_page_sidecar_cast_mismatch(tmp_path: Path) -> None:
    """The gold cast PASSes, but dropping a card from the page (without un-emitting it in
    the sidecar) must hard-fail — the page/sidecar single-source invariant. Guards the
    false-PASS risk where page and sidecar are derived from divergent selections."""
    root = tmp_path / "run-mismatch"
    page = _gold_page()
    page["key_characters"] = page["key_characters"][1:]  # drop the top emitted card
    _write_run(root, page, _gold_sidecar())

    score = evaluate_run(root)[0]
    codes = {f.code for f in score.findings}
    assert "semantics.page_sidecar_cast_mismatch" in codes
    assert score.status == STATUS_FAIL


def test_rubric_catches_emitted_without_merge_rank(tmp_path: Path) -> None:
    """An emitted sidecar row missing a merge_rank is a recorded-selection defect."""
    root = tmp_path / "run-no-rank"
    sidecar = _gold_sidecar()
    for candidate in sidecar[0]["candidates"]:
        if candidate.get("emitted"):
            candidate["merge_rank"] = None
            break
    _write_run(root, _gold_page(), sidecar)

    score = evaluate_run(root)[0]
    codes = {f.code for f in score.findings}
    assert "semantics.sidecar_emitted_without_rank" in codes
    assert score.status == STATUS_FAIL


def test_rubric_catches_emit_order_vs_merge_rank_mismatch(tmp_path: Path) -> None:
    """Same cast set, but the page emit-order disagrees with the sidecar merge_rank order:
    a reproducibility defect the set-only check used to false-PASS."""
    root = tmp_path / "run-order"
    page = _gold_page()
    cast = page["key_characters"]
    page["key_characters"] = [cast[1], cast[0], *cast[2:]]  # swap the top two emitted cards
    _write_run(root, page, _gold_sidecar())

    score = evaluate_run(root)[0]
    codes = {f.code for f in score.findings}
    assert "semantics.page_sidecar_order_mismatch" in codes
    assert "semantics.page_sidecar_cast_mismatch" not in codes  # set still agrees
    assert score.status == STATUS_FAIL


def test_diff_reports_overview_and_cast_deltas(tmp_path: Path) -> None:
    candidate_root = tmp_path / "run-candidate"
    baseline_root = tmp_path / "run-baseline"
    _write_run(candidate_root, _gold_page(), _gold_sidecar())
    _write_run(baseline_root, _degraded_page(), _degraded_sidecar())

    report = diff_runs(baseline_root, candidate_root)
    assert report["instance_count"] == 1
    instance = report["instances"][0]
    assert instance["instance_id"] == "instance-scholomance"
    assert instance["change"] == "changed"
    fields = instance["fields"]
    assert fields["overview"]["changed"] is True
    assert fields["overview"]["word_delta"] > 0
    added = set(fields["key_characters"]["added"])
    assert {"Rattlegore", "Jandice Barov", "Lilian Voss"} <= added
    assert "Darkmaster Gandling" not in added
    assert set(fields["decision_sidecar"]["emitted_added"]) == added
    assert instance["rationale"]


def test_diff_main_writes_reports_with_notes(tmp_path: Path) -> None:
    candidate_root = tmp_path / "run-candidate"
    baseline_root = tmp_path / "run-baseline"
    _write_run(candidate_root, _gold_page(), _gold_sidecar())
    _write_run(baseline_root, _degraded_page(), _degraded_sidecar())
    notes_path = tmp_path / "rationale.txt"
    notes_path.write_text("Promoted after cast + overview fixes.", encoding="utf-8")

    rc = diff_main(
        [
            "--baseline",
            str(baseline_root),
            "--candidate",
            str(candidate_root),
            "--notes",
            str(notes_path),
        ]
    )
    assert rc == 0
    diff_json = candidate_root / "reports" / "instance_run_diff.json"
    diff_md = candidate_root / "reports" / "instance_run_diff.md"
    assert diff_json.exists()
    assert diff_md.exists()
    payload = json.loads(diff_json.read_text(encoding="utf-8"))
    assert payload["operator_notes"] == "Promoted after cast + overview fixes."
    assert "Operator notes" in diff_md.read_text(encoding="utf-8")
