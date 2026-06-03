"""Map Slice B cluster slugs to stable questline card ids (ql-*)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.discovery.storyline_html import _slugify

_WPL_ZONE_ID = "zone-western-plaguelands"
_WPL_REGISTRY_PATH = Path("tests/fixtures/pilot/western_plaguelands_questline_registry.json")

_ARC_KEYWORD_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    ("andorhal", frozenset({"andorhal"})),
    ("mender", frozenset({"mender", "cenarion"})),
    ("hearthglen", frozenset({"hearthglen", "tirion", "fordring"})),
    ("northridge", frozenset({"northridge", "lumber", "redpine"})),
    ("gahrron", frozenset({"gahrron", "withering", "cauldron"})),
)

_WPL_REGISTRY_RULES: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("ql-andorhal-alliance", "alliance", frozenset({"andorhal"})),
    ("ql-andorhal-horde", "horde", frozenset({"andorhal"})),
    ("ql-menders-stead-healing", "shared", frozenset({"mender", "cenarion", "healing the plagueland"})),
    ("ql-hearthglen-tirion-legacy", "shared", frozenset({"hearthglen", "tirion", "fordring", "highlord"})),
)


def load_pilot_questline_registry(zone_id: str) -> dict[str, Any] | None:
    if zone_id != _WPL_ZONE_ID or not _WPL_REGISTRY_PATH.exists():
        return None
    blob = json.loads(_WPL_REGISTRY_PATH.read_text(encoding="utf-8"))
    return blob if isinstance(blob, dict) else None


def _match_registry_arc(
    *,
    cluster_id: str,
    cluster_title: str,
    faction: str,
    registry: dict[str, Any],
) -> dict[str, Any] | None:
    blob = f"{cluster_id} {cluster_title} {faction}".lower()
    arcs_by_id = {
        str(arc.get("id", "")).strip(): arc
        for arc in registry.get("included_arcs", [])
        if isinstance(arc, dict) and arc.get("id")
    }
    for arc_id, arc_faction, keywords in _WPL_REGISTRY_RULES:
        if arc_faction != faction and not (arc_faction == "shared" or faction == "shared"):
            continue
        if any(keyword in blob for keyword in keywords):
            matched = arcs_by_id.get(arc_id)
            if matched:
                return matched
    return None


def _heuristic_card_id(cluster_title: str, faction: str) -> tuple[str, str | None]:
    blob = cluster_title.lower()
    for label, keywords in _ARC_KEYWORD_RULES:
        if any(keyword in blob for keyword in keywords):
            slug = _slugify(f"{label}-{faction}" if faction in {"alliance", "horde"} else label)
            return f"ql-{slug}", None
    return "", None


def map_cluster_to_card_id(
    *,
    zone_id: str,
    cluster_id: str,
    cluster_title: str,
    faction: str,
    registry: dict[str, Any] | None = None,
) -> tuple[str, str | None, str, bool]:
    """Return (card_id, registry_arc_id, display_title, suppress_continued_card)."""
    registry_blob = registry if registry is not None else load_pilot_questline_registry(zone_id)
    matched = (
        _match_registry_arc(
            cluster_id=cluster_id,
            cluster_title=cluster_title,
            faction=faction,
            registry=registry_blob,
        )
        if registry_blob
        else None
    )
    if matched:
        arc_id = str(matched.get("id", "")).strip()
        display_title = str(matched.get("title", cluster_title)).strip()
        return arc_id, arc_id, display_title, True

    heuristic_id, _ = _heuristic_card_id(cluster_title, faction)
    if heuristic_id:
        return heuristic_id, None, cluster_title, False

    fallback_id = f"cluster-{cluster_id}"
    return fallback_id, None, cluster_title, False
