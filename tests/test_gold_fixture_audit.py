"""WS-E: gold-fixture audit regression guard + Classic-contamination acceptance (D-3).

The offline audit must stay clean (gold fixtures retail-correct + contract-valid). The
run-draft test is an xfail acceptance criterion that flips to passing once S3 (the
retail/Classic crawl filter) excludes Classic-only entities from the live cast.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_gold_fixtures import (
    audit_instance_page_gold,
    audit_offline,
    audit_zone_questline_gold,
)

_RUN_DRAFT = Path(
    "artifacts/runs/test-run-wpl-1/data/drafts/instance_page/instance-scholomance.json"
)
_CLASSIC_SCHOLOMANCE = {
    "Ravenian",
    "Doctor Theolen Krastinov",
    "Professor Slate",
    "Weldon Barov",
    "Lord Alexei Barov",
}


def test_offline_audit_has_no_errors() -> None:
    errors = [f for f in audit_offline() if f.level == "error"]
    assert errors == [], errors


def test_instance_gold_audit_clean() -> None:
    assert [f for f in audit_instance_page_gold() if f.level == "error"] == []


def test_zone_questline_gold_audit_clean() -> None:
    assert [f for f in audit_zone_questline_gold() if f.level == "error"] == []


@pytest.mark.xfail(
    reason="S3 retail/Classic crawl filter not yet implemented; the live run still ingests "
    "Classic-only Scholomance NPCs. Flip to strict once S3 lands.",
    strict=False,
)
def test_run_draft_excludes_classic_bosses() -> None:
    if not _RUN_DRAFT.exists():
        pytest.skip("requires local test-run-wpl-1 draft")
    page = json.loads(_RUN_DRAFT.read_text(encoding="utf-8"))
    emitted = {str(card.get("name", "")) for card in page.get("key_characters") or []}
    leaked = emitted & _CLASSIC_SCHOLOMANCE
    assert not leaked, f"Classic-only NPCs in live cast: {sorted(leaked)}"
