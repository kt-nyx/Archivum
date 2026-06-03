"""Tests for the Western Plaguelands pilot instance gold (Scholomance).

Mirror of test_pilot_questline_gold_standard.py for the instance path: the committed
instance gold is the regression anchor for Slice I6 promotion quality. It must parse to the
canonical InstancePage contract, pass release-gate validation, pass every deterministic
instance detector, and stay aligned with the pilot source manifest + decision sidecar.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.contracts.models import INSTANCE_MIN_KEY_CHARACTERS, InstancePage
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
from pipeline.validate.engine import validate_payload

PILOT_DIR = Path("tests/fixtures/pilot")
GOLD_PATH = PILOT_DIR / "instance_page_scholomance_gold.json"
DECISIONS_PATH = PILOT_DIR / "instance_key_character_decisions_scholomance_gold.json"
SOURCE_MANIFEST_PATH = PILOT_DIR / "source_manifest.json"

_INSTANCE_NAME = "Scholomance"
_GATE_CONTEXT = {"release_gate": True, "fact_check_profile": "off"}


def _load_gold() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def _load_roster() -> list[dict]:
    blob = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    row = next(r for r in blob if r["instance_id"] == "instance-scholomance")
    return list(row["candidates"])


def _load_source_manifest() -> list[dict]:
    return json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))


def test_instance_gold_matches_contract() -> None:
    parsed = InstancePage.model_validate(_load_gold())
    assert parsed.instance_id == "instance-scholomance"
    assert parsed.parent_zone_id == "zone-western-plaguelands"
    assert parsed.instance_type == "dungeon"
    assert INSTANCE_MIN_KEY_CHARACTERS <= len(parsed.key_characters)
    assert {card.role for card in parsed.key_characters} == {"enemy"}


def test_instance_gold_passes_release_gate() -> None:
    report = validate_payload("instance_page", _load_gold(), _GATE_CONTEXT)
    assert report.passed is True
    assert report.hard_fail_count == 0
    assert report.warn_count == 0


def test_instance_gold_passes_prose_detectors() -> None:
    gold = _load_gold()
    at_a_glance = gold["at_a_glance"]
    overview = gold["overview"]
    assert not is_generic_at_a_glance(at_a_glance)
    assert not is_generic_overview(overview)
    assert lint_at_a_glance(at_a_glance, instance_name=_INSTANCE_NAME) == []
    assert lint_overview(overview, instance_name=_INSTANCE_NAME) == []
    assert lint_passthrough_fragment(overview) == []
    for section in gold["history_sections"]:
        assert lint_passthrough_fragment(section["body"]) == []
    for card in gold["key_characters"]:
        assert not is_generic_key_character_summary(card["summary"])
        assert (
            lint_key_character_summary(
                card["summary"], boss_name=card["name"], instance_name=_INSTANCE_NAME
            )
            == []
        )


def test_instance_gold_ids_align_with_manifest() -> None:
    gold = _load_gold()
    manifest = _load_source_manifest()
    scholomance_rows = [row for row in manifest if row["entity_id"] == "instance-scholomance"]
    assert len(scholomance_rows) == 1
    assert scholomance_rows[0]["entity_type"] == "instance"
    assert scholomance_rows[0]["parent_zone_id"] == gold["parent_zone_id"]
    assert gold["instance_id"] == scholomance_rows[0]["entity_id"]


def test_instance_gold_role_diversity_ok() -> None:
    gold = _load_gold()
    roster = _load_roster()
    severity, reason = assess_role_diversity(gold["key_characters"], roster)
    assert severity == "ok", reason


def test_instance_gold_sidecar_emitted_matches_cast() -> None:
    gold = _load_gold()
    roster = _load_roster()
    gold_names = {card["name"] for card in gold["key_characters"]}
    emitted_names = {c["name"] for c in roster if c.get("emitted")}
    assert emitted_names == gold_names
    # The roster is a superset that documents non-emitted candidates too.
    assert len(roster) >= len(gold_names)
    assert {c["name"] for c in roster} >= gold_names
