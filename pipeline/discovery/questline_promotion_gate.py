"""Shared questline promotion gates for validate, semantics, and quality reports (Slice E)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.discovery.pilot_questline_registry import (
    WPL_ZONE_ID,
    structural_expectations_for_zone,
)
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
    pilot_expectations: Any | None


def _load_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _title_matches_entry_keyword(title: str) -> bool:
    normalized = _normalize_title(title)
    return any(keyword in normalized for keyword in ENTRY_QUEST_TITLE_KEYWORDS)


def load_questline_run_artifacts(run_root: Path, zone_id: str) -> QuestlineRunArtifacts:
    draft_path = run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json"
    cards: list[dict[str, Any]] = []
    if draft_path.exists():
        draft = _load_json(draft_path)
        if isinstance(draft, dict):
            raw = draft.get("major_questlines", [])
            cards = [row for row in raw if isinstance(row, dict)]

    included_cluster_ids: list[str] = []
    rankings_path = run_root / "data" / "discovery" / "zone_quest_cluster_rankings.json"
    rankings_blob = _load_json(rankings_path)
    if isinstance(rankings_blob, list):
        by_zone = load_included_cluster_ids_by_zone(rankings_blob)
        included_cluster_ids = by_zone.get(zone_id, [])

    metadata_by_cluster: dict[str, dict[str, Any]] = {}
    metadata_path = run_root / "data" / "discovery" / "zone_questline_card_metadata.json"
    metadata_blob = _load_json(metadata_path)
    if isinstance(metadata_blob, list):
        for row in metadata_blob:
            if not isinstance(row, dict):
                continue
            if str(row.get("zone_id", "")).strip() != zone_id:
                continue
            cluster_id = str(row.get("cluster_id", "")).strip()
            if cluster_id:
                metadata_by_cluster[cluster_id] = row

    card_id_to_cluster_id = {
        str(row.get("card_id", "")).strip(): str(row.get("cluster_id", "")).strip()
        for row in metadata_by_cluster.values()
        if str(row.get("card_id", "")).strip() and str(row.get("cluster_id", "")).strip()
    }

    excluded_cluster_ids: set[str] = set()
    decisions_path = run_root / "data" / "decisions" / "questline_inclusion_decisions.json"
    decisions_blob = _load_json(decisions_path)
    if isinstance(decisions_blob, list):
        for row in decisions_blob:
            if not isinstance(row, dict):
                continue
            if str(row.get("subject_type", "")) != "questline_cluster":
                continue
            features = row.get("features") or {}
            row_zone = str(features.get("zone_id", row.get("zone_id", ""))).strip()
            if row_zone and row_zone != zone_id:
                continue
            if str(row.get("final_decision", "")).strip() == "exclude":
                cluster_id = str(row.get("subject_id", "")).strip()
                if cluster_id:
                    excluded_cluster_ids.add(cluster_id)

    v3_rows: list[dict[str, Any]] = []
    v3_path = run_root / "data" / "discovery" / "zone_quest_graph_v3.json"
    v3_blob = _load_json(v3_path)
    if isinstance(v3_blob, list):
        v3_rows = [row for row in v3_blob if isinstance(row, dict)]

    pilot_expectations = structural_expectations_for_zone(zone_id)
    return QuestlineRunArtifacts(
        zone_id=zone_id,
        cards=cards,
        included_cluster_ids=included_cluster_ids,
        metadata_by_cluster=metadata_by_cluster,
        card_id_to_cluster_id=card_id_to_cluster_id,
        excluded_cluster_ids=excluded_cluster_ids,
        v3_quest_rows=v3_rows,
        pilot_expectations=pilot_expectations,
    )


def cluster_id_from_card_id(card_id: str, card_id_to_cluster_id: dict[str, str]) -> str:
    mapped = card_id_to_cluster_id.get(str(card_id).strip())
    if mapped:
        return mapped
    normalized = str(card_id).replace("cluster-", "", 1)
    if normalized.endswith("-continued"):
        return normalized[: -len("-continued")]
    return normalized


def check_questline_promotion(
    artifacts: QuestlineRunArtifacts,
    *,
    pilot_strict: bool = False,
    require_rankings: bool = False,
    require_evidence_coverage: bool = False,
    covered_cluster_ids: set[str] | None = None,
) -> list[str]:
    """Return hard-fail error messages."""
    errors: list[str] = []
    cards = artifacts.cards
    card_ids = [str(card.get("id", "")).strip() for card in cards if str(card.get("id", "")).strip()]

    for index, card in enumerate(cards):
        title = str(card.get("title", "")).strip() or f"card[{index}]"
        if str(card.get("include_decision", "")).strip() not in {"include", ""}:
            errors.append(f"questline card {title!r} include_decision is not include")
        chain_refs = card.get("chain_refs", [])
        if isinstance(chain_refs, list) and len(chain_refs) > _MAX_CHAIN_REFS:
            errors.append(
                f"questline card {title!r} chain_refs exceeds cap ({len(chain_refs)} > {_MAX_CHAIN_REFS})"
            )

    for card_id in card_ids:
        if card_id.endswith("-continued"):
            errors.append(f"questline card id must not use -continued suffix: {card_id!r}")

    if artifacts.included_cluster_ids:
        if len(cards) != len(artifacts.included_cluster_ids):
            errors.append(
                "major_questlines count "
                f"({len(cards)}) does not match included_cluster_ids ({len(artifacts.included_cluster_ids)})"
            )
        mapped_clusters = {
            cluster_id_from_card_id(card_id, artifacts.card_id_to_cluster_id) for card_id in card_ids
        }
        expected = set(artifacts.included_cluster_ids)
        if mapped_clusters != expected and artifacts.card_id_to_cluster_id:
            errors.append(
                "major_questlines cluster mapping "
                f"(got {sorted(mapped_clusters)}, expected {sorted(expected)})"
            )
    elif require_rankings:
        errors.append("zone_quest_cluster_rankings missing or has no included clusters for zone")

    for card in cards:
        card_id = str(card.get("id", "")).strip()
        cluster_id = cluster_id_from_card_id(card_id, artifacts.card_id_to_cluster_id)
        if cluster_id in artifacts.excluded_cluster_ids:
            errors.append(f"questline card {card_id!r} maps to excluded cluster {cluster_id!r}")

    for cluster_id, meta in artifacts.metadata_by_cluster.items():
        expected_card_id = str(meta.get("card_id", "")).strip()
        if not expected_card_id:
            continue
        matching = [card for card in cards if cluster_id_from_card_id(str(card.get("id", "")), artifacts.card_id_to_cluster_id) == cluster_id]
        for card in matching:
            if str(card.get("id", "")).strip() != expected_card_id:
                errors.append(
                    f"questline card id {card.get('id')!r} does not match metadata card_id {expected_card_id!r} "
                    f"for cluster {cluster_id!r}"
                )
        if str(meta.get("suppress_continued_card", "")).lower() in {"true", "1"} or meta.get(
            "suppress_continued_card"
        ) is True:
            for card_id in card_ids:
                if cluster_id_from_card_id(card_id, artifacts.card_id_to_cluster_id) == cluster_id:
                    if card_id.endswith("-continued"):
                        errors.append(
                            f"continued card emitted despite suppress_continued_card for {cluster_id!r}"
                        )

    if require_evidence_coverage and artifacts.included_cluster_ids:
        covered = covered_cluster_ids or set()
        missing = [cluster_id for cluster_id in artifacts.included_cluster_ids if cluster_id not in covered]
        if missing:
            errors.append(
                "included clusters missing quest_cluster_lore evidence: " + ", ".join(sorted(missing))
            )

    expectations = artifacts.pilot_expectations
    if pilot_strict and expectations:
        if len(cards) != expectations.expected_card_count:
            errors.append(
                f"pilot questline card count {len(cards)} != expected {expectations.expected_card_count}"
            )
        emitted_ids = set(card_ids)
        if emitted_ids != set(expectations.included_card_ids):
            errors.append(
                "pilot questline card ids "
                f"(got {sorted(emitted_ids)}, expected {sorted(expectations.included_card_ids)})"
            )
        if emitted_ids & set(expectations.excluded_card_ids):
            errors.append(
                "pilot excluded registry card ids present in draft: "
                + ", ".join(sorted(emitted_ids & set(expectations.excluded_card_ids)))
            )
        for card in cards:
            card_id = str(card.get("id", "")).strip()
            expected_anchor = expectations.anchor_by_card_id.get(card_id, "")
            if expected_anchor and str(card.get("start_anchor", "")).strip() != expected_anchor:
                errors.append(
                    f"pilot start_anchor for {card_id!r} "
                    f"(got {card.get('start_anchor')!r}, expected {expected_anchor!r})"
                )

        v3_node_ids = {
            str(row.get("node_id", "")).strip()
            for row in artifacts.v3_quest_rows
            if str(row.get("zone_id", "")) == artifacts.zone_id
            and str(row.get("node_type", "")) == "quest"
            and row.get("node_id")
        }
        order_by_node = {
            str(row.get("node_id", "")).strip(): int(row.get("order_in_cluster", 0) or 0)
            for row in artifacts.v3_quest_rows
            if str(row.get("zone_id", "")) == artifacts.zone_id
            and str(row.get("node_type", "")) == "quest"
        }
        for card in cards:
            card_id = str(card.get("id", "")).strip()
            chain_refs = card.get("chain_refs", [])
            if not isinstance(chain_refs, list):
                continue
            last_order = -1
            for node_id in chain_refs:
                node_id = str(node_id).strip()
                if node_id and node_id not in v3_node_ids:
                    errors.append(f"pilot chain_ref {node_id!r} missing from v3 graph for card {card_id!r}")
                order = order_by_node.get(node_id, last_order)
                if order < last_order:
                    errors.append(f"pilot chain_refs order regresses for card {card_id!r} at {node_id!r}")
                last_order = order

    return errors


def warn_questline_promotion(artifacts: QuestlineRunArtifacts) -> list[str]:
    """Return soft warning messages."""
    warnings: list[str] = []
    expectations = artifacts.pilot_expectations

    for card in artifacts.cards:
        title = str(card.get("title", "")).strip()
        anchor = str(card.get("start_anchor", "")).strip()
        if anchor and title and _normalize_title(anchor) == _normalize_title(title):
            if not _title_matches_entry_keyword(anchor):
                warnings.append(
                    f"start_anchor equals card title and matches no entry-quest pattern: {title!r}"
                )

    if expectations:
        for card in artifacts.cards:
            card_id = str(card.get("id", "")).strip()
            registry_refs = set(expectations.primary_chain_refs_by_card_id.get(card_id, []))
            if not registry_refs:
                continue
            chain_refs = {
                str(value).strip()
                for value in card.get("chain_refs", [])
                if isinstance(card.get("chain_refs"), list) and str(value).strip()
            }
            if chain_refs and not chain_refs.intersection(registry_refs):
                warnings.append(
                    f"pilot chain_refs for {card_id!r} share no primary refs with registry"
                )

    return warnings


def default_pilot_strict_for_zone(
    zone_id: str,
    pilot_questline_gate: bool | None,
    *,
    run_root: Path | None = None,
) -> bool:
    if pilot_questline_gate is not None:
        return pilot_questline_gate
    if zone_id != WPL_ZONE_ID:
        return False
    if run_root is not None:
        return (run_root / "data" / "discovery" / "zone_quest_cluster_rankings.json").exists()
    return False
