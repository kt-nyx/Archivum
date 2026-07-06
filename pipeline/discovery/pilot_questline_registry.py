"""Pilot questline registry loader — gold/QA scaffolding, NOT the general path.

The curated registry exists only for pilot zones (WPL): it is a *validator/override*
that pins the gold card set for promotion gates and supplies curated arc ids, titles,
and start anchors. The general questline path (structural clustering -> significance
scoring -> cap trim -> generic ``ql-<slug>`` ids) must produce structurally valid
cards for any zone **without** a registry; ``tests/test_questline_general_path.py``
guards that. Never add registry data for non-pilot zones to make output "right" —
fix the general path instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WPL_ZONE_ID = "zone-western-plaguelands"

_REGISTRY_PATHS: dict[str, Path] = {
    WPL_ZONE_ID: Path(__file__).resolve().parent.parent
    / "data"
    / "pilot"
    / "western_plaguelands_questline_registry.json",
}

# Back-compat for tests that referenced fixtures path.
LEGACY_FIXTURE_REGISTRY_PATH = Path(
    "tests/fixtures/pilot/western_plaguelands_questline_registry.json"
)


def registry_path_for_zone(zone_id: str) -> Path | None:
    return _REGISTRY_PATHS.get(zone_id.strip())


def load_registry(zone_id: str) -> dict[str, Any] | None:
    path = registry_path_for_zone(zone_id)
    if path is None or not path.exists():
        if zone_id == WPL_ZONE_ID and LEGACY_FIXTURE_REGISTRY_PATH.exists():
            blob = json.loads(LEGACY_FIXTURE_REGISTRY_PATH.read_text(encoding="utf-8"))
            return blob if isinstance(blob, dict) else None
        return None
    blob = json.loads(path.read_text(encoding="utf-8"))
    return blob if isinstance(blob, dict) else None


def included_card_ids(registry: dict[str, Any]) -> set[str]:
    return {
        str(arc.get("id", "")).strip()
        for arc in registry.get("included_arcs", [])
        if isinstance(arc, dict) and arc.get("id")
    }


def excluded_card_ids(registry: dict[str, Any]) -> set[str]:
    return {
        str(arc.get("id", "")).strip()
        for arc in registry.get("excluded_arcs", [])
        if isinstance(arc, dict) and arc.get("id")
    }


def anchor_by_card_id(registry: dict[str, Any]) -> dict[str, str]:
    anchors: dict[str, str] = {}
    for section in ("included_arcs", "excluded_arcs"):
        for arc in registry.get(section, []):
            if not isinstance(arc, dict):
                continue
            arc_id = str(arc.get("id", "")).strip()
            anchor = str(arc.get("start_anchor", "")).strip()
            if arc_id and anchor:
                anchors[arc_id] = anchor
    return anchors


def title_by_card_id(registry: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for section in ("included_arcs", "excluded_arcs"):
        for arc in registry.get(section, []):
            if not isinstance(arc, dict):
                continue
            arc_id = str(arc.get("id", "")).strip()
            title = str(arc.get("title", "")).strip()
            if arc_id and title:
                titles[arc_id] = title
    return titles


def primary_chain_refs_by_card_id(registry: dict[str, Any]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for arc in registry.get("included_arcs", []):
        if not isinstance(arc, dict):
            continue
        arc_id = str(arc.get("id", "")).strip()
        if arc_id:
            refs[arc_id] = [
                str(value) for value in arc.get("chain_refs") or [] if str(value).strip()
            ]
    return refs


@dataclass(frozen=True)
class PilotQuestlineExpectations:
    zone_id: str
    expected_card_count: int
    included_card_ids: frozenset[str]
    excluded_card_ids: frozenset[str]
    anchor_by_card_id: dict[str, str]
    title_by_card_id: dict[str, str]
    primary_chain_refs_by_card_id: dict[str, list[str]]


def structural_expectations_for_zone(zone_id: str) -> PilotQuestlineExpectations | None:
    registry = load_registry(zone_id)
    if not registry:
        return None
    gap = registry.get("pipeline_gap_analysis") or {}
    expected = int(gap.get("expected_included_card_count", 0) or 0)
    if expected <= 0:
        expected = len(registry.get("included_arcs") or [])
    return PilotQuestlineExpectations(
        zone_id=zone_id,
        expected_card_count=expected,
        included_card_ids=frozenset(included_card_ids(registry)),
        excluded_card_ids=frozenset(excluded_card_ids(registry)),
        anchor_by_card_id=anchor_by_card_id(registry),
        title_by_card_id=title_by_card_id(registry),
        primary_chain_refs_by_card_id=primary_chain_refs_by_card_id(registry),
    )
