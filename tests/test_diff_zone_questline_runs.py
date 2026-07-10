from __future__ import annotations

import json

import pytest

from scripts.diff_zone_questline_runs import main


def _write_zone(run_root, zone_id: str) -> None:
    target = run_root / "data" / "drafts" / "zone_page"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{zone_id}.json").write_text(json.dumps({"major_questlines": []}))


def test_diff_autodetects_single_shared_zone(tmp_path) -> None:
    baseline, candidate = tmp_path / "a", tmp_path / "b"
    _write_zone(baseline, "zone-example")
    _write_zone(candidate, "zone-example")
    assert main(["--baseline", str(baseline), "--candidate", str(candidate)]) == 0


def test_diff_requires_zone_when_ambiguous(tmp_path) -> None:
    baseline, candidate = tmp_path / "a", tmp_path / "b"
    _write_zone(baseline, "zone-one")
    _write_zone(baseline, "zone-two")
    _write_zone(candidate, "zone-one")
    with pytest.raises(SystemExit):
        main(["--baseline", str(baseline), "--candidate", str(candidate)])
