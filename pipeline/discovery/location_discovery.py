"""Generic staged location-discovery decisions and bounded coverage selection."""

from __future__ import annotations

import re
from typing import Any, Literal

from pipeline.common.text_ids import slugify
from pipeline.contracts.models import (
    EntityKind,
    LocationCoverageStatus,
    LocationSelectionDecision,
    LocationSelectionState,
)

LOCATION_PROBE_BATCH_SIZE = 4
LOCATION_PROBE_CAP = 24
LOCATION_PROFILE_CAP = 12
LOCATION_DESIRED_CARD_COUNT = 8
LOCATION_MIN_VIABLE_CARDS = 3


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def name_in_seed_text(name: str, seed_text: str) -> bool:
    if not name.strip() or not seed_text.strip():
        return False
    return _normalize_name(name) in _normalize_name(seed_text)


def build_zone_seed_text(snapshots: list[dict[str, Any]], zone_id: str) -> str:
    """Collect zone narrative text for generic questline significance inputs."""
    from pipeline.common.text_normalize import clean_wiki_snippet

    seed_roles = {
        "maps_subregions",
        "history",
        "geography_edit",
        "geography",
        "quests_or_storyline",
    }
    parts: list[str] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("entity_id", "")).strip() != zone_id:
            continue
        if str(snapshot.get("entity_type", "")).strip() != "zone":
            continue
        if str(snapshot.get("auxiliary_role", "")).strip():
            continue
        blocks = snapshot.get("section_blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            role = _normalize_name(str(block.get("section_role", ""))).replace(" ", "_")
            if role not in seed_roles and "history" not in role:
                continue
            snippet = clean_wiki_snippet(str(block.get("text", "")))
            if snippet:
                parts.append(snippet)
    return " ".join(parts)


def location_candidate_rank(source_relation: str, name: str) -> tuple[int, str]:
    """Stable preliminary ordering from the source relationship, never title facts."""
    role = _normalize_name(source_relation).replace(" ", "_")
    if "history" in role:
        priority = 0
    elif any(marker in role for marker in ("map", "subregion", "geography")):
        priority = 1
    elif any(marker in role for marker in ("quest", "story", "current")):
        priority = 2
    else:
        priority = 3
    return priority, _normalize_name(name)


def build_location_candidate_decision(
    *,
    zone_id: str,
    location_id: str,
    name: str,
    source_link: str,
    source_relation: str,
    candidate_rank: int,
    entity_kind: EntityKind,
    entity_kind_decision_id: str,
    source_ids: list[str],
    reason_codes: list[str],
) -> LocationSelectionDecision:
    """Create the initial broad-discovery state for one valid outbound link."""
    state = (
        LocationSelectionState.REJECTED
        if entity_kind not in {EntityKind.PLACE, EntityKind.UNKNOWN}
        else LocationSelectionState.CANDIDATE
    )
    reasons = list(reason_codes)
    if state is LocationSelectionState.REJECTED:
        reasons.append("entity_kind_not_place")
    return LocationSelectionDecision(
        decision_id=f"location-selection-{slugify(zone_id)}-{slugify(name)}",
        zone_id=zone_id,
        location_id=location_id,
        name=name,
        source_link=source_link,
        source_relation=source_relation or "other",
        candidate_rank=candidate_rank,
        state=state,
        entity_kind=entity_kind,
        entity_kind_decision_id=entity_kind_decision_id,
        source_ids=source_ids,
        reason_codes=reasons,
    )


def profile_evidence_count(snapshot: dict[str, Any]) -> int:
    blocks = snapshot.get("section_blocks")
    if not isinstance(blocks, list):
        return 0
    return sum(
        1 for block in blocks if isinstance(block, dict) and str(block.get("text", "")).strip()
    )


def profile_establishes_zone_record(snapshot: dict[str, Any], zone_name: str) -> bool:
    """Whether the location's own fetched page affirmatively names its parent zone."""
    if not zone_name.strip():
        return False
    text_parts = [str(snapshot.get("body", ""))]
    blocks = snapshot.get("section_blocks")
    if isinstance(blocks, list):
        text_parts.extend(str(block.get("text", "")) for block in blocks if isinstance(block, dict))
    return name_in_seed_text(zone_name, " ".join(text_parts))


def select_profiled_locations(
    decisions: list[LocationSelectionDecision],
    *,
    desired_card_count: int = LOCATION_DESIRED_CARD_COUNT,
) -> list[LocationSelectionDecision]:
    """Choose direct profiles with generic history/geography/current coverage."""
    viable = [
        row
        for row in decisions
        if row.state is LocationSelectionState.PROFILE
        and row.entity_kind is EntityKind.PLACE
        and row.zone_record == "on_zone"
        and row.profile_source_id
        and row.profile_evidence_count > 0
    ]
    viable.sort(key=lambda row: (row.candidate_rank, _normalize_name(row.name)))

    def family(row: LocationSelectionDecision) -> str:
        role = _normalize_name(row.source_relation).replace(" ", "_")
        if "history" in role:
            return "history"
        if any(marker in role for marker in ("map", "subregion", "geography")):
            return "geography"
        if any(marker in role for marker in ("quest", "story", "current")):
            return "current"
        return "other"

    selected_ids = {
        row.location_id for row in decisions if row.state is LocationSelectionState.SELECTED
    }
    for wanted in ("history", "geography", "current", "other"):
        row = next(
            (
                row
                for row in viable
                if row.location_id not in selected_ids and family(row) == wanted
            ),
            None,
        )
        if row is not None and len(selected_ids) < desired_card_count:
            selected_ids.add(row.location_id)
    for row in viable:
        if len(selected_ids) >= desired_card_count:
            break
        selected_ids.add(row.location_id)
    return [
        row.model_copy(update={"state": LocationSelectionState.SELECTED})
        if row.location_id in selected_ids
        else row
        for row in decisions
    ]


def location_coverage_status(
    *,
    zone_id: str,
    decisions: list[LocationSelectionDecision],
    probes_attempted: int,
    profiles_attempted: int,
    probe_cap: int = LOCATION_PROBE_CAP,
    profile_cap: int = LOCATION_PROFILE_CAP,
    desired_card_count: int = LOCATION_DESIRED_CARD_COUNT,
) -> LocationCoverageStatus:
    selected_count = sum(1 for row in decisions if row.state is LocationSelectionState.SELECTED)
    exhausted = probes_attempted >= probe_cap or profiles_attempted >= profile_cap
    status: Literal["coverage_met", "insufficient_viable_locations"] = (
        "coverage_met"
        if selected_count >= LOCATION_MIN_VIABLE_CARDS
        else "insufficient_viable_locations"
    )
    reasons = []
    if status == "insufficient_viable_locations":
        reasons = [
            "insufficient_viable_locations",
            "retrieval_budget_exhausted" if exhausted else "candidate_pool_exhausted",
        ]
    return LocationCoverageStatus(
        zone_id=zone_id,
        desired_card_count=desired_card_count,
        selected_count=selected_count,
        probe_cap=probe_cap,
        profile_cap=profile_cap,
        probes_attempted=probes_attempted,
        profiles_attempted=profiles_attempted,
        status=status,
        attempted_candidate_ids=[row.location_id for row in decisions],
        reason_codes=reasons,
    )
