"""Map Slice B clusters to stable questline card ids (ql-*).

Generalized (run review): clusters are matched to registry arcs by **quest-membership
overlap** rather than zone-specific keyword tables. The registry arc supplies the stable
``ql-*`` id, display title, and start anchor. Clusters that match no included arc are
dropped (no raw ``cluster-*`` id is ever emitted for a pilot zone). Zones without a
registry fall back to a generic ``ql-<slug>`` minted from the cluster identity.
"""

from __future__ import annotations

from typing import Any

from pipeline.discovery.pilot_questline_registry import WPL_ZONE_ID, load_registry
from pipeline.discovery.storyline_html import _slugify

_WPL_ZONE_ID = WPL_ZONE_ID

# Minimum cluster<->arc node-id overlap required to bind a cluster to a registry arc.
_MIN_ARC_OVERLAP = 2


def load_pilot_questline_registry(zone_id: str) -> dict[str, Any] | None:
    return load_registry(zone_id)


def _faction_compatible(arc_faction: str, faction: str) -> bool:
    arc_faction = (arc_faction or "shared").strip().lower()
    faction = (faction or "shared").strip().lower()
    return arc_faction == faction or arc_faction == "shared" or faction == "shared"


def _arc_member_refs(arc: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in ("chain_refs", "overflow_chain_refs", "shared_beat_refs"):
        refs |= {str(ref).strip() for ref in arc.get(key, []) if str(ref).strip()}
    return refs


def match_registry_arc_by_membership(
    member_node_ids: list[str],
    *,
    faction: str,
    registry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the included registry arc whose quest membership best covers the cluster.

    General and keyword-free: picks the faction-compatible included arc with the greatest
    node-id overlap, provided the overlap clears ``_MIN_ARC_OVERLAP`` (or covers a majority
    of the cluster's quests for short clusters). Returns ``None`` when no arc qualifies.
    """
    members = {str(node_id).strip() for node_id in member_node_ids if str(node_id).strip()}
    if not members or not registry:
        return None
    threshold = min(_MIN_ARC_OVERLAP, len(members))
    best_arc: dict[str, Any] | None = None
    best_overlap = 0
    for arc in registry.get("included_arcs", []):
        if not isinstance(arc, dict) or not str(arc.get("id", "")).strip():
            continue
        if not _faction_compatible(str(arc.get("faction", "shared")), faction):
            continue
        overlap = len(members & _arc_member_refs(arc))
        if overlap > best_overlap:
            best_overlap = overlap
            best_arc = arc
    if best_arc is not None and best_overlap >= threshold:
        return best_arc
    return None


def map_cluster_to_card_id(
    *,
    zone_id: str,
    cluster_id: str,
    cluster_title: str,
    faction: str,
    member_node_ids: list[str] | None = None,
    registry: dict[str, Any] | None = None,
) -> tuple[str, str | None, str, bool]:
    """Return ``(card_id, registry_arc_id, display_title, suppress_continued_card)``.

    ``card_id`` is empty when the cluster matches no included registry arc in a pilot zone
    (the caller drops it). Non-registry zones get a generic ``ql-<slug>`` id.
    """
    registry_blob = registry if registry is not None else load_pilot_questline_registry(zone_id)
    matched = match_registry_arc_by_membership(
        member_node_ids or [],
        faction=faction,
        registry=registry_blob,
    )
    if matched:
        arc_id = str(matched.get("id", "")).strip()
        display_title = str(matched.get("title", cluster_title)).strip() or cluster_title
        return arc_id, arc_id, display_title, True

    if registry_blob is not None:
        # Pilot zone with a registry but no membership match: drop rather than emit a raw id.
        return "", None, cluster_title, False

    # No registry for this zone: mint a stable, generic ql-* id from the cluster identity.
    slug = _slugify(cluster_title)
    if faction in {"alliance", "horde"} and f"-{faction}" not in slug:
        slug = f"{slug}-{faction}"
    return (f"ql-{slug}" if slug else f"ql-{cluster_id}"), None, cluster_title, False
