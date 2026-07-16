"""Family-first, evidence-bearing story-arc selection (Slice 5)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pipeline.contracts.models import (
    ZONE_MAX_TOTAL_QUESTLINE_CARDS,
    ZONE_MIN_TOTAL_QUESTLINE_CARDS,
    ArcCandidate,
    ArcCoverage,
    ArcFamily,
    ArcFamilyDecision,
    ArcSignalEvidence,
    QuestlineArcSelectionArtifact,
)
from pipeline.discovery.questline_cluster import normalize_quest_title

_FACTION_SUFFIX_RE = re.compile(r"\s*\((alliance|horde)\)\s*$", re.IGNORECASE)
_THEME_STOP_WORDS = frozenset(
    {"about", "after", "against", "between", "from", "into", "that", "their", "there", "these", "they", "this", "through", "with", "your"}
)


def _faction_and_base_title(title: str, faction: str) -> tuple[str, str | None]:
    match = _FACTION_SUFFIX_RE.search(title.strip())
    suffix_faction = match.group(1).lower() if match else ""
    base_title = _FACTION_SUFFIX_RE.sub("", title).strip() or title.strip()
    variant = suffix_faction or (faction if faction in {"alliance", "horde"} else "")
    return base_title, variant or None


def _signal(
    signal: Literal[
        "shared_hub",
        "recurring_actor",
        "recurring_organization",
        "prerequisite_followup",
        "conflict_theme",
        "faction",
        "phase_expansion",
    ],
    values: set[str],
    refs: list[str],
) -> ArcSignalEvidence:
    return ArcSignalEvidence(signal=signal, values=sorted(values), evidence_refs=sorted(set(refs)))


def _theme_tokens(records: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for record in records:
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", str(record.get("description", "")).casefold()):
            if token not in _THEME_STOP_WORDS:
                tokens.add(token)
    return tokens


def _candidate_from_component(
    summary: dict[str, Any],
    *,
    records_by_node: dict[str, dict[str, Any]],
    rows_by_cluster: dict[str, list[dict[str, Any]]],
) -> ArcCandidate:
    candidate_id = str(summary["cluster_id"])
    node_ids = [str(node_id) for node_id in summary.get("quest_node_ids", []) if str(node_id)]
    records = [records_by_node[node_id] for node_id in node_ids if node_id in records_by_node]
    missing_records = [node_id for node_id in node_ids if node_id not in records_by_node]
    rows = rows_by_cluster.get(candidate_id, [])
    faction = str(summary.get("faction", "shared")).casefold()
    base_title, faction_variant = _faction_and_base_title(str(summary.get("title", candidate_id)), faction)
    hubs = {str(record.get("start_location", "")).strip() for record in records} - {""}
    actors = {
        str(record.get("start_npc", "")).strip() or str(record.get("end_npc", "")).strip()
        for record in records
    } - {""}
    organizations = {str(record.get("reputation_org", "")).strip() for record in records} - {""}
    theme = _theme_tokens(records)
    member_set = set(node_ids)
    cross_refs = {
        str(ref).strip()
        for record in records
        for field in ("previous", "next")
        for ref in record.get(field, []) or []
        if str(ref).strip()
    } - member_set
    internal_edges = sum(
        1
        for record in records
        for field in ("previous", "next")
        for ref in record.get(field, []) or []
        if str(ref).strip() in member_set
    )
    chain_heads = sum(1 for record in records if not (record.get("previous") or []))
    setup = 2 if chain_heads and hubs else (1 if chain_heads else 0)
    connectivity = min(2, internal_edges)
    continuity = 2 if len(theme) >= 5 else (1 if theme else 0)
    zone_relevance = 2 if hubs else (1 if rows else 0)
    cast_faction = min(2, int(bool(actors)) + int(bool(organizations or faction_variant)))
    coverage = 2 if len(node_ids) >= 3 else (1 if len(node_ids) >= 2 else 0)
    coherent_score = float(setup + connectivity + continuity + zone_relevance + cast_faction + coverage)
    signals = [
        _signal("shared_hub", hubs, node_ids),
        _signal("recurring_actor", actors, node_ids),
        _signal("recurring_organization", organizations, node_ids),
        _signal("prerequisite_followup", cross_refs, node_ids),
        _signal("conflict_theme", theme, node_ids),
        _signal("faction", {faction_variant} if faction_variant else set(), node_ids),
        _signal("phase_expansion", {str(record.get("expansion") or record.get("phase") or "").strip() for record in records} - {""}, node_ids),
    ]
    reason_codes = ["coherent_arc_score", f"score:{int(coherent_score)}"]
    if missing_records:
        reason_codes.append("missing_quest_records")
    if len(node_ids) == 1:
        if setup + zone_relevance + cast_faction >= 5:
            reason_codes.append("single_quest_high_signal_exception")
        else:
            reason_codes.append("single_quest_insufficient_signal")
    return ArcCandidate(
        candidate_id=candidate_id,
        zone_id=str(summary["zone_id"]),
        component_ids=[candidate_id],
        quest_node_ids=node_ids,
        base_title=base_title,
        faction_variant=faction_variant,
        phase_variant=next((signal.values[0] for signal in signals if signal.signal == "phase_expansion" and signal.values), None),
        signal_evidence=signals,
        coherent_score=coherent_score,
        reason_codes=reason_codes,
    )


def _values(candidate: ArcCandidate, signal: str) -> set[str]:
    return {value for item in candidate.signal_evidence if item.signal == signal for value in item.values}


def _relationship(left: ArcCandidate, right: ArcCandidate) -> tuple[Literal["merge", "keep_separate"], list[ArcSignalEvidence], dict[str, str] | None]:
    common: list[ArcSignalEvidence] = []
    for signal in ("shared_hub", "recurring_actor", "recurring_organization", "prerequisite_followup", "conflict_theme"):
        values = _values(left, signal) & _values(right, signal)
        if values:
            common.append(_signal(signal, values, left.quest_node_ids + right.quest_node_ids))
    same_title = normalize_quest_title(left.base_title) == normalize_quest_title(right.base_title)
    distinct_variants = (left.faction_variant, left.phase_variant) != (right.faction_variant, right.phase_variant)
    if same_title and len(common) >= 2:
        return "merge", common, None
    if same_title and distinct_variants and common:
        return "merge", common, None
    if same_title and len(common) == 1:
        # Bounded adjudication: only a fixed enum and the exact structured signals are retained.
        return "keep_separate", common, {
            "prompt_class": "arc_family_ambiguity.v1",
            "ruling": "keep_separate",
            "evidence": common[0].signal,
        }
    return "keep_separate", common, None


def _family_id(zone_id: str, members: list[ArcCandidate]) -> str:
    # Quest-title normalization preserves apostrophes for matching, while contract IDs permit only
    # lowercase alphanumeric segments separated by single hyphens.
    stem = re.sub(r"[^a-z0-9]+", "-", normalize_quest_title(members[0].base_title)).strip("-") or "arc"
    return f"arc-{zone_id}-{stem}-{members[0].candidate_id}"


def select_zone_arc_families(
    *,
    zone_id: str,
    cluster_summaries: list[dict[str, Any]],
    v3_rows: list[dict[str, Any]],
    quest_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Build candidates, resolve families, then apply coverage and budget at family level."""
    records_by_node = {str(row.get("node_id", "")): row for row in quest_records if str(row.get("zone_id", "")) == zone_id}
    rows_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in v3_rows:
        if str(row.get("zone_id", "")) == zone_id and row.get("node_type") == "quest":
            rows_by_cluster[str(row.get("cluster_id", ""))].append(row)
    candidates = [
        _candidate_from_component(summary, records_by_node=records_by_node, rows_by_cluster=rows_by_cluster)
        for summary in cluster_summaries
        if str(summary.get("zone_id", "")) == zone_id and summary.get("cluster_id")
    ]
    candidates.sort(key=lambda candidate: candidate.candidate_id)
    parent = {candidate.candidate_id: candidate.candidate_id for candidate in candidates}
    decisions: list[ArcFamilyDecision] = []
    def root(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            ruling, evidence, adjudication = _relationship(left, right)
            decisions.append(ArcFamilyDecision(decision_id=f"arc-decision-{left.candidate_id}-{right.candidate_id}", zone_id=zone_id, decision=ruling, candidate_ids=[left.candidate_id, right.candidate_id], reason_codes=["structured_signals_agree"] if ruling == "merge" else ["insufficient_shared_campaign_evidence"], signal_evidence=evidence, adjudication=adjudication))
            if ruling == "merge":
                parent[root(right.candidate_id)] = root(left.candidate_id)
    grouped: dict[str, list[ArcCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[root(candidate.candidate_id)].append(candidate)
    families: list[ArcFamily] = []
    selected: list[str] = []
    exclusions: list[ArcFamilyDecision] = []
    remaining = ZONE_MAX_TOTAL_QUESTLINE_CARDS
    selected_labels: set[str] = set()
    ordered_groups = sorted(grouped.values(), key=lambda members: (-max(member.coherent_score for member in members), members[0].candidate_id))
    for members in ordered_groups:
        members.sort(key=lambda member: (-member.coherent_score, member.candidate_id))
        family = ArcFamily(family_id=_family_id(zone_id, members), zone_id=zone_id, base_title=members[0].base_title, candidate_ids=[member.candidate_id for member in members], signal_evidence=[signal for member in members for signal in member.signal_evidence if signal.values], coherent_score=max(member.coherent_score for member in members))
        families.append(family)
        eligible = [
            member
            for member in members
            if "missing_quest_records" not in member.reason_codes
            and (
                len(member.quest_node_ids) > 1
                or "single_quest_high_signal_exception" in member.reason_codes
            )
        ]
        if not eligible:
            reason_code = (
                "missing_quest_records"
                if any("missing_quest_records" in member.reason_codes for member in members)
                else "single_quest_insufficient_signal"
            )
            exclusions.append(ArcFamilyDecision(decision_id=f"arc-exclude-{family.family_id}", zone_id=zone_id, decision="exclude", candidate_ids=family.candidate_ids, family_id=family.family_id, reason_codes=[reason_code], signal_evidence=[]))
            continue
        for member in eligible:
            if remaining <= 0:
                exclusions.append(ArcFamilyDecision(decision_id=f"arc-exclude-{member.candidate_id}", zone_id=zone_id, decision="exclude", candidate_ids=[member.candidate_id], family_id=family.family_id, reason_codes=["family_coverage_budget_exhausted"], signal_evidence=[]))
                continue
            if member is not eligible[0] and not (member.faction_variant or member.phase_variant):
                exclusions.append(ArcFamilyDecision(decision_id=f"arc-exclude-{member.candidate_id}", zone_id=zone_id, decision="exclude", candidate_ids=[member.candidate_id], family_id=family.family_id, reason_codes=["parallel_variant_not_distinct_playable_path"], signal_evidence=[]))
                continue
            label = " ".join(
                part
                for part in (member.base_title, member.faction_variant, member.phase_variant)
                if part
            ).casefold()
            if label in selected_labels:
                exclusions.append(ArcFamilyDecision(decision_id=f"arc-exclude-{member.candidate_id}", zone_id=zone_id, decision="exclude", candidate_ids=[member.candidate_id], family_id=family.family_id, reason_codes=["duplicate_normalized_variant_label"], signal_evidence=[]))
                continue
            selected.append(member.candidate_id)
            selected_labels.add(label)
            decisions.append(ArcFamilyDecision(decision_id=f"arc-include-{member.candidate_id}", zone_id=zone_id, decision="include", candidate_ids=[member.candidate_id], family_id=family.family_id, reason_codes=["family_coverage_selected"] if member is eligible[0] else ["distinct_faction_or_phase_variant_selected"], signal_evidence=member.signal_evidence))
            remaining -= 1
    return ([candidate.model_dump(mode="json") for candidate in candidates], [family.model_dump(mode="json") for family in families], [decision.model_dump(mode="json") for decision in decisions + exclusions], selected)


def arc_selection_artifact(
    *, candidates: list[dict[str, Any]], families: list[dict[str, Any]], decisions: list[dict[str, Any]], selected_candidate_ids_by_zone: dict[str, list[str]],
) -> dict[str, Any]:
    parsed_candidates = [ArcCandidate.model_validate(row) for row in candidates]
    parsed_families = [ArcFamily.model_validate(row) for row in families]
    parsed_decisions = [ArcFamilyDecision.model_validate(row) for row in decisions]
    rankings_by_zone: dict[str, list[str]] = defaultdict(list)
    for family in sorted(
        parsed_families, key=lambda row: (row.zone_id, -row.coherent_score, row.family_id)
    ):
        rankings_by_zone[family.zone_id].append(family.family_id)
    coverage = [
        ArcCoverage(
            zone_id=zone_id,
            status=(
                "coverage_met"
                if len(selected_ids) >= ZONE_MIN_TOTAL_QUESTLINE_CARDS
                else "insufficient_viable_arc_variants"
            ),
            selected_candidate_ids=selected_ids,
            attempted_candidate_ids=[
                candidate.candidate_id
                for candidate in parsed_candidates
                if candidate.zone_id == zone_id
            ],
            reason_codes=(
                ["family_coverage_met"]
                if len(selected_ids) >= ZONE_MIN_TOTAL_QUESTLINE_CARDS
                else ["insufficient_viable_arc_variants", "all_candidates_and_exclusions_recorded"]
            ),
        )
        for zone_id, selected_ids in sorted(selected_candidate_ids_by_zone.items())
    ]
    return QuestlineArcSelectionArtifact(
        candidates=parsed_candidates,
        families=parsed_families,
        decisions=[row for row in parsed_decisions if row.decision != "exclude"],
        exclusions=[row for row in parsed_decisions if row.decision == "exclude"],
        selected_candidate_ids_by_zone=selected_candidate_ids_by_zone,
        family_rankings_by_zone=dict(rankings_by_zone),
        coverage=coverage,
    ).model_dump(mode="json")


def load_arc_selection(path: Path) -> QuestlineArcSelectionArtifact:
    import json

    from pydantic import ValidationError
    try:
        return QuestlineArcSelectionArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise ValueError(f"questline_arc_selection reader: expected discovery.questline_significance artifact questline_arc_selection.v1 at {path}: {exc}") from exc


def selected_candidate_ids_by_zone(path: Path) -> dict[str, list[str]]:
    return load_arc_selection(path).selected_candidate_ids_by_zone


def arc_membership(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    artifact = load_arc_selection(path)
    candidates = {row.candidate_id: row.model_dump(mode="json") for row in artifact.candidates}
    families = {candidate_id: family.model_dump(mode="json") for family in artifact.families for candidate_id in family.candidate_ids}
    return candidates, families
