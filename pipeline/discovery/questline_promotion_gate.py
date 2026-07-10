"""Zone-neutral questline promotion checks shared by validation and reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.discovery.questline_anchor import ENTRY_QUEST_TITLE_KEYWORDS
from pipeline.discovery.questline_significance import load_included_cluster_ids_by_zone

_MAX_CHAIN_REFS = 12


@dataclass
class QuestlineRunArtifacts:
    zone_id: str
    cards: list[dict[str, Any]]
    included_cluster_ids: list[str]
    metadata_by_cluster: dict[str, dict[str, Any]]
    card_id_to_cluster_id: dict[str, str]
    excluded_cluster_ids: set[str]
    v3_quest_rows: list[dict[str, Any]]


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _title_matches_entry_keyword(title: str) -> bool:
    return any(keyword in _normalize_title(title) for keyword in ENTRY_QUEST_TITLE_KEYWORDS)


def load_questline_run_artifacts(run_root: Path, zone_id: str) -> QuestlineRunArtifacts:
    cards: list[dict[str, Any]] = []
    draft = _load_json(run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json")
    if isinstance(draft, dict):
        cards = [row for row in draft.get("major_questlines", []) if isinstance(row, dict)]

    included_cluster_ids: list[str] = []
    rankings = _load_json(run_root / "data" / "discovery" / "zone_quest_cluster_rankings.json")
    if isinstance(rankings, list):
        included_cluster_ids = load_included_cluster_ids_by_zone(rankings).get(zone_id, [])

    metadata_by_cluster: dict[str, dict[str, Any]] = {}
    metadata = _load_json(run_root / "data" / "discovery" / "zone_questline_card_metadata.json")
    if isinstance(metadata, list):
        for row in metadata:
            if isinstance(row, dict) and str(row.get("zone_id", "")).strip() == zone_id:
                cluster_id = str(row.get("cluster_id", "")).strip()
                if cluster_id:
                    metadata_by_cluster[cluster_id] = row

    excluded_cluster_ids: set[str] = set()
    decisions = _load_json(run_root / "data" / "decisions" / "questline_inclusion_decisions.json")
    if isinstance(decisions, list):
        for row in decisions:
            if not isinstance(row, dict) or str(row.get("subject_type", "")) != "questline_cluster":
                continue
            if str(row.get("zone_id", "")).strip() == zone_id and row.get("final_decision") == "exclude":
                excluded_cluster_ids.add(str(row.get("subject_id", "")).strip())

    v3 = _load_json(run_root / "data" / "discovery" / "zone_quest_graph_v3.json")
    v3_quest_rows = [row for row in v3 if isinstance(row, dict)] if isinstance(v3, list) else []
    card_id_to_cluster_id = {
        str(row.get("card_id", "")).strip(): cluster_id
        for cluster_id, row in metadata_by_cluster.items()
        if str(row.get("card_id", "")).strip()
    }
    return QuestlineRunArtifacts(
        zone_id=zone_id,
        cards=cards,
        included_cluster_ids=included_cluster_ids,
        metadata_by_cluster=metadata_by_cluster,
        card_id_to_cluster_id=card_id_to_cluster_id,
        excluded_cluster_ids=excluded_cluster_ids,
        v3_quest_rows=v3_quest_rows,
    )


def cluster_id_from_card_id(card_id: str, card_id_to_cluster_id: dict[str, str]) -> str:
    normalized = str(card_id).strip()
    if normalized in card_id_to_cluster_id:
        return card_id_to_cluster_id[normalized]
    if normalized.startswith("ql-"):
        normalized = normalized[3:]
    if "-segment-" in normalized:
        normalized = normalized.split("-segment-", 1)[0]
    return normalized


def check_questline_promotion(
    artifacts: QuestlineRunArtifacts,
    *,
    require_rankings: bool = False,
    require_evidence_coverage: bool = False,
    covered_cluster_ids: set[str] | None = None,
) -> list[str]:
    """Return generalized structural and evidence failures for one zone."""
    errors: list[str] = []
    cards = artifacts.cards
    card_ids = [str(card.get("id", "")).strip() for card in cards]
    nonempty_ids = [card_id for card_id in card_ids if card_id]
    if len(nonempty_ids) != len(set(nonempty_ids)):
        errors.append("major_questlines contains duplicate card ids")

    rows_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for row in artifacts.v3_quest_rows:
        if str(row.get("zone_id", "")).strip() != artifacts.zone_id:
            continue
        if str(row.get("node_type", "")) != "quest":
            continue
        rows_by_cluster.setdefault(str(row.get("cluster_id", "")).strip(), []).append(row)
    for rows in rows_by_cluster.values():
        rows.sort(key=lambda row: int(row.get("order_in_cluster", 0) or 0))

    emitted_clusters: set[str] = set()
    for index, card in enumerate(cards):
        card_id = str(card.get("id", "")).strip()
        title = str(card.get("title", "")).strip() or f"card[{index}]"
        if artifacts.metadata_by_cluster and not card_id.startswith("ql-"):
            errors.append(f"questline card {title!r} id is not a graph-derived ql-* id")
        if str(card.get("include_decision", "")).strip() not in {"include", ""}:
            errors.append(f"questline card {title!r} include_decision is not include")
        chain_refs = card.get("chain_refs", [])
        if not isinstance(chain_refs, list) or not chain_refs:
            errors.append(f"questline card {title!r} has no chain_refs")
            continue
        if len(chain_refs) > _MAX_CHAIN_REFS:
            errors.append(f"questline card {title!r} chain_refs exceeds cap")
        cluster_id = cluster_id_from_card_id(card_id, artifacts.card_id_to_cluster_id)
        emitted_clusters.add(cluster_id)
        if cluster_id in artifacts.excluded_cluster_ids:
            errors.append(f"questline card {card_id!r} maps to excluded cluster {cluster_id!r}")
        metadata = artifacts.metadata_by_cluster.get(cluster_id, {})
        expected_id = str(metadata.get("card_id", "")).strip()
        if expected_id and card_id != expected_id and not card_id.startswith(f"{expected_id}-segment-"):
            errors.append(f"questline card {card_id!r} does not derive from metadata for {cluster_id!r}")
        expected_refs = [str(value).strip() for value in metadata.get("ordered_chain_refs", [])]
        if expected_refs and any(str(ref).strip() not in expected_refs for ref in chain_refs):
            errors.append(f"questline card {card_id!r} contains a chain ref outside its cluster")
        rows = rows_by_cluster.get(cluster_id, [])
        if rows:
            known_ids = {str(row.get("node_id", "")).strip() for row in rows}
            if any(str(ref).strip() not in known_ids for ref in chain_refs):
                errors.append(f"questline card {card_id!r} contains an unknown chain ref")
            positions = {str(row.get("node_id", "")).strip(): pos for pos, row in enumerate(rows)}
            order = [positions[str(ref).strip()] for ref in chain_refs if str(ref).strip() in positions]
            if order != sorted(order):
                errors.append(f"questline card {card_id!r} chain refs are out of graph order")

    if artifacts.included_cluster_ids:
        expected = set(artifacts.included_cluster_ids)
        if emitted_clusters != expected:
            errors.append(
                f"major_questlines cluster mapping (got {sorted(emitted_clusters)}, expected {sorted(expected)})"
            )
    elif require_rankings:
        errors.append("zone_quest_cluster_rankings missing or has no included clusters for zone")

    if require_evidence_coverage and artifacts.included_cluster_ids:
        missing = set(artifacts.included_cluster_ids) - set(covered_cluster_ids or set())
        if missing:
            errors.append("included clusters missing quest_cluster_lore evidence: " + ", ".join(sorted(missing)))
    return errors


def warn_questline_promotion(artifacts: QuestlineRunArtifacts) -> list[str]:
    warnings: list[str] = []
    for card in artifacts.cards:
        title = str(card.get("title", "")).strip()
        anchor = str(card.get("start_anchor", "")).strip()
        if anchor and title and _normalize_title(anchor) == _normalize_title(title):
            if not _title_matches_entry_keyword(anchor):
                warnings.append(f"start_anchor equals card title and matches no entry-quest pattern: {title!r}")
    return warnings
