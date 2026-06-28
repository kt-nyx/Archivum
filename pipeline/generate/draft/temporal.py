"""Boundary-relative temporal evidence classification for draft assembly.

The classifier labels source snippets by how they relate to what the player is walking into.
It deliberately avoids expansion/era alias lists and "latest era" ordering. Deterministic rules
only use structural signals such as quest position, source section role, source kind, current
instance roster evidence, and category policy. Prose whose temporal relation cannot be proven from
structure is sent to a boundary-relative LLM adjudicator when available; otherwise it remains
``ambiguous_temporal`` and downstream page fields exclude it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.wiki_category_registry import CategorySignal, classify_page_categories
from pipeline.generate.draft.llm import llm_json_with_retry

PRE_ENTRY_HISTORY = "pre_entry_history"
ENTRY_STATE = "entry_state"
ACTIVE_STORYLINE = "active_storyline"
ACTIVE_STORYLINE_OUTCOME = "active_storyline_outcome"
POST_ACTIVE_LORE = "post_active_lore"
EXCLUDED_NONCANON = "excluded_noncanon"
AMBIGUOUS_TEMPORAL = "ambiguous_temporal"

HISTORY_BACKGROUND = "history_background"
HISTORY_SETUP_BRIDGE = "history_setup_bridge"
HISTORY_EXCLUDED_OUTCOME = "history_excluded_outcome"
HISTORY_EXCLUDED_POST_ACTIVE = "history_excluded_post_active"
HISTORY_NOT_APPLICABLE = "history_not_applicable"

HISTORY_ELIGIBLE = frozenset({HISTORY_BACKGROUND, HISTORY_SETUP_BRIDGE})

TEMPORAL_SCOPES = frozenset(
    {
        PRE_ENTRY_HISTORY,
        ENTRY_STATE,
        ACTIVE_STORYLINE,
        ACTIVE_STORYLINE_OUTCOME,
        POST_ACTIVE_LORE,
        EXCLUDED_NONCANON,
        AMBIGUOUS_TEMPORAL,
    }
)

_TEMPORAL_SCOPE_VALUES = (
    PRE_ENTRY_HISTORY,
    ENTRY_STATE,
    ACTIVE_STORYLINE,
    ACTIVE_STORYLINE_OUTCOME,
    POST_ACTIVE_LORE,
    EXCLUDED_NONCANON,
    AMBIGUOUS_TEMPORAL,
)

_HISTORY_ELIGIBILITY_VALUES = (
    HISTORY_BACKGROUND,
    HISTORY_SETUP_BRIDGE,
    HISTORY_EXCLUDED_OUTCOME,
    HISTORY_EXCLUDED_POST_ACTIVE,
    HISTORY_NOT_APPLICABLE,
)

_ENTRY_ROLE_MARKERS = (
    "lead",
    "introduction",
    "adventure guide",
    "adventure_guide",
    "dungeon ",
    "dungeon_",
    "faculty",
    "boss",
    "denizens",
    "encounter",
)
_POST_LORE_ROLE_MARKERS = (
    "exploring azeroth",
    "exploring_azeroth",
    "novel",
    "novella",
    "short story",
    "short_story",
    "manga",
    "comic",
    "report",
    "later appearances",
    "later_appearances",
)
_EXCLUDED_ROLE_MARKERS = (
    "in the rpg",
    "in_the_rpg",
    "roleplaying game",
    "rpg",
    "achievements",
    "removed",
    "deprecated",
    "classic",
    "non canon",
    "non-canon",
)
_ACTIVE_FIELD_NAMES = frozenset({"questline_pool", "quest_cluster_lore", "quest_lore"})
_CURRENT_FIELD_NAMES = frozenset({"currently_input", "at_a_glance_input", "boss_pool"})
_PROFILE_CONTEXT_FIELD_NAMES = frozenset(
    {"faction_pool", "location_pool", "instance_lore_pool", "parent_lore_pool", "related_lore_pool"}
)
_BOUNDARY_SNIPPET_LIMIT = 360
_BOUNDARY_DIGEST_LIMIT = 1800
_PROMPT_SNIPPET_LIMIT = 1200
_SETUP_QUEST_LIMIT = 2
_OUTCOME_QUEST_LIMIT = 2
_MIXED_VALID_CATEGORY_TOKENS = (
    "dungeon",
    "raid",
    "subzone",
    "zone",
    "city",
    "cities",
    "town",
    "village",
    "settlement",
    "quest hub",
    "faction",
    "organization",
    "character",
    "npc",
    "boss",
    "instance",
    "landmark",
    "ruin",
    "stronghold",
    "lore",
)
_DIRECT_NONCANON_TOKENS = ("non-canon", "non canon")
_DIRECT_EXCLUSION_TOKENS = (*_DIRECT_NONCANON_TOKENS, "removed")
_DEFER_CATEGORY_TOKENS = ("rpg", "roleplaying", "speculation", "potentially out-of-date")
_CONTRACT_MATCH_FIELDS = (
    "current_locations",
    "current_factions",
    "current_threats",
    "active_conflicts",
    "current_objectives",
    "active_storylines",
    "current_inhabitants",
    "current_controller",
    "active_encounters",
)
_CONTRACT_ID_KEYS = (
    "location_id",
    "faction_id",
    "character_id",
    "npc_id",
    "entity_id",
    "cluster_id",
    "quest_ref",
)


@dataclass(frozen=True)
class TemporalClassification:
    scope: str
    confidence: float
    reason: str
    boundary_id: str = ""
    structural_hint: str = ""
    event_label: str = ""
    fallback_mode: str = "deterministic"
    history_eligibility: str = HISTORY_NOT_APPLICABLE
    history_reason: str = ""


@dataclass
class CanonicalEvidenceRecord:
    canonical_evidence_id: str
    subject_id: str
    subject_type: str
    source_id: str
    source_categories: list[str]
    source_title: str
    snippet: str
    boundary: dict[str, Any]
    appearances: list[dict[str, Any]]
    refs: list[dict[str, Any]]
    structural_classifications: list[TemporalClassification]
    classification: TemporalClassification | None = None


@dataclass
class EntryStateContract:
    """Structured description of what this page considers current at player entry."""

    entity_id: str
    entity_type: str
    name: str
    run_id: str = "unknown"
    contract_id: str = ""
    current_locations: list[dict[str, Any]] = field(default_factory=list)
    current_factions: list[dict[str, Any]] = field(default_factory=list)
    current_threats: list[dict[str, Any]] = field(default_factory=list)
    active_conflicts: list[dict[str, Any]] = field(default_factory=list)
    current_objectives: list[dict[str, Any]] = field(default_factory=list)
    active_storylines: list[dict[str, Any]] = field(default_factory=list)
    current_inhabitants: list[dict[str, Any]] = field(default_factory=list)
    current_controller: list[dict[str, Any]] = field(default_factory=list)
    active_encounters: list[dict[str, Any]] = field(default_factory=list)
    excluded_outcome_hints: list[dict[str, Any]] = field(default_factory=list)
    source_anchor_refs: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "run_id": self.run_id,
            "current_locations": self.current_locations,
            "current_factions": self.current_factions,
            "current_threats": self.current_threats,
            "active_conflicts": self.active_conflicts,
            "current_objectives": self.current_objectives,
            "active_storylines": self.active_storylines,
            "current_inhabitants": self.current_inhabitants,
            "current_controller": self.current_controller,
            "active_encounters": self.active_encounters,
            "excluded_outcome_hints": self.excluded_outcome_hints,
            "source_anchor_refs": self.source_anchor_refs,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def temporal_scope_allowed(
    item: dict[str, Any],
    allowed: set[str] | frozenset[str],
    *,
    include_unscoped: bool = True,
) -> bool:
    scope = str(item.get("temporal_scope", "")).strip()
    if not scope:
        return include_unscoped
    return scope in allowed


def filter_temporal_items(
    items: list[dict[str, Any]],
    allowed: set[str] | frozenset[str],
    *,
    include_unscoped: bool = True,
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if temporal_scope_allowed(item, allowed, include_unscoped=include_unscoped)
    ]


def history_eligibility_allowed(
    item: dict[str, Any],
    *,
    include_unscoped: bool = True,
) -> bool:
    """Return whether an item can support background/history cards.

    Temporal scope answers "when does this evidence sit relative to entry state"; this answers
    whether the paragraph belongs in a history section. In particular, an ``entry_state`` history
    paragraph can be a setup bridge if it explains the state the player is walking into.
    """
    scope = str(item.get("temporal_scope", "")).strip()
    eligibility = str(item.get("history_eligibility", "")).strip()
    if eligibility:
        return eligibility in HISTORY_ELIGIBLE
    if scope in {
        POST_ACTIVE_LORE,
        ACTIVE_STORYLINE_OUTCOME,
        EXCLUDED_NONCANON,
        AMBIGUOUS_TEMPORAL,
    }:
        return False
    if not scope:
        return include_unscoped
    return scope == PRE_ENTRY_HISTORY


def filter_history_items(
    items: list[dict[str, Any]],
    *,
    include_unscoped: bool = True,
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if history_eligibility_allowed(item, include_unscoped=include_unscoped)
    ]


def exclude_temporal_items(
    items: list[dict[str, Any]],
    excluded: set[str] | frozenset[str] = frozenset(
        {POST_ACTIVE_LORE, EXCLUDED_NONCANON, AMBIGUOUS_TEMPORAL}
    ),
    *,
    include_unscoped: bool = True,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in items:
        scope = str(item.get("temporal_scope", "")).strip()
        if not scope:
            if include_unscoped:
                kept.append(item)
            continue
        if scope not in excluded:
            kept.append(item)
    return kept


def enrich_evidence_temporal_metadata(
    evidence_rows: list[dict[str, Any]],
    *,
    fact_packs_by_entity: dict[str, dict[str, Any]] | None = None,
    source_snapshots: list[dict[str, Any]] | None = None,
    questline_card_metadata: dict[str, dict[str, Any]] | None = None,
    quest_records_by_node: dict[str, dict[str, Any]] | None = None,
    run_id: str = "",
    return_entry_state_contract_decisions: bool = False,
    return_boundary_decisions: bool = False,
    return_canonical_decisions: bool = False,
) -> tuple[Any, ...]:
    """Return evidence rows plus temporal and content-boundary decision rows."""
    snapshot_categories = _snapshot_categories_by_source(source_snapshots or [])
    card_index = _quest_card_index(questline_card_metadata or {})
    contracts, entry_state_contract_decisions = build_entry_state_contracts(
        evidence_rows,
        fact_packs_by_entity=fact_packs_by_entity or {},
        source_snapshots=source_snapshots or [],
        questline_card_metadata=questline_card_metadata or {},
        quest_records_by_node=quest_records_by_node or {},
        run_id=run_id,
    )
    boundaries, boundary_decisions = _content_boundaries_from_entry_state_contracts(
        contracts,
        run_id=run_id,
    )

    enriched_rows, canonical_records = _build_canonical_evidence_records(
        evidence_rows,
        boundaries=boundaries,
        snapshot_categories=snapshot_categories,
    )

    for record in canonical_records:
        record.classification = _with_canonical_history_defaults(
            classify_canonical_evidence_record(record, quest_card_index=card_index),
            appearances=record.appearances,
        )

    llm_candidates = [
        record
        for record in canonical_records
        if record.classification is not None
        and _needs_canonical_llm_adjudication(record.classification, record)
    ]
    if llm_candidates and not _llm_temporal_adjudication_disabled():
        overrides = adjudicate_canonical_temporal_classifications_llm(llm_candidates)
        for record in canonical_records:
            override = overrides.get(record.canonical_evidence_id)
            if override is not None:
                record.classification = _with_canonical_history_defaults(
                    override,
                    appearances=record.appearances,
                )

    decisions: list[dict[str, Any]] = []
    canonical_decisions: list[dict[str, Any]] = []
    scopes_by_row: dict[int, list[str]] = {}
    build_meta_by_row: dict[int, dict[str, Any]] = {}
    boundary_by_row: dict[int, dict[str, Any]] = {}
    for record in canonical_records:
        if record.classification is None:
            continue
        classification = record.classification
        canonical_decisions.append(_canonical_decision_row(record, classification, run_id=run_id))
        for ref in record.refs:
            item = ref["item"]
            build_meta = ref["build_meta"]
            row_index = int(ref["row_index"])
            item["canonical_evidence_id"] = record.canonical_evidence_id
            item["temporal_scope"] = classification.scope
            item["temporal_confidence"] = classification.confidence
            item["temporal_reason"] = classification.reason
            item["temporal_event_label"] = classification.event_label
            item["history_eligibility"] = classification.history_eligibility
            item["history_reason"] = classification.history_reason
            scopes_by_row.setdefault(row_index, []).append(classification.scope)
            build_meta_by_row[row_index] = build_meta
            boundary_by_row[row_index] = record.boundary
            decisions.append(
                {
                    "subject_id": str(record.subject_id)
                    or str(build_meta.get("subject_zone_id", "")),
                    "subject_type": str(record.subject_type),
                    "run_id": run_id
                    or str(build_meta.get("run_id", "")).strip()
                    or "unknown",
                    "source_id": str(record.source_id),
                    "canonical_evidence_id": record.canonical_evidence_id,
                    "field_name": str(ref["field_name"]),
                    "row_index": row_index,
                    "item_index": int(ref["item_index"]),
                    "temporal_scope": classification.scope,
                    "temporal_confidence": classification.confidence,
                    "temporal_reason": classification.reason,
                    "temporal_boundary_id": classification.boundary_id,
                    "temporal_structural_hint": classification.structural_hint,
                    "temporal_event_label": classification.event_label,
                    "temporal_fallback_mode": classification.fallback_mode,
                    "history_eligibility": classification.history_eligibility,
                    "history_reason": classification.history_reason,
                }
            )
    for row_index, scopes in scopes_by_row.items():
        build_meta = build_meta_by_row[row_index]
        boundary = boundary_by_row[row_index]
        build_meta["temporal_scope"] = _dominant_scope(scopes)
        build_meta["temporal_confidence"] = "0.8"
        build_meta["temporal_boundary_id"] = str(boundary.get("boundary_id", ""))
    outputs: list[Any] = [enriched_rows, decisions]
    if return_entry_state_contract_decisions:
        outputs.append(entry_state_contract_decisions)
    if return_boundary_decisions:
        outputs.append(boundary_decisions)
    if return_canonical_decisions:
        outputs.append(canonical_decisions)
    return tuple(outputs)


def _build_canonical_evidence_records(
    evidence_rows: list[dict[str, Any]],
    *,
    boundaries: dict[str, dict[str, Any]],
    snapshot_categories: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[CanonicalEvidenceRecord]]:
    enriched_rows: list[dict[str, Any]] = []
    records_by_key: dict[tuple[str, str, str, str, str], CanonicalEvidenceRecord] = {}
    records: list[CanonicalEvidenceRecord] = []
    for row_index, row in enumerate(evidence_rows):
        if not isinstance(row, dict):
            continue
        out = copy.deepcopy(row)
        subject_id = str(out.get("subject_id", "")).strip()
        subject_type = str(out.get("subject_type", "")).strip()
        build_meta = out.setdefault("build_meta", {})
        if not isinstance(build_meta, dict):
            build_meta = {}
            out["build_meta"] = build_meta
        source_id = _canonical_source_id(out, {})
        categories = snapshot_categories.get(source_id, [])
        boundary = boundaries.get(subject_id) or _fallback_boundary(subject_id, subject_type)
        items = out.get("evidence_items")
        if not isinstance(items, list):
            enriched_rows.append(out)
            continue

        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            key = _canonical_evidence_key(out, item)
            if key is None:
                continue
            canonical_id = _canonical_evidence_id(key)
            item["canonical_evidence_id"] = canonical_id
            appearance = _canonical_appearance(
                row=out,
                item=item,
                row_index=row_index,
                item_index=item_index,
            )
            record = records_by_key.get(key)
            if record is None:
                item_source_id = _canonical_source_id(out, item)
                record = CanonicalEvidenceRecord(
                    canonical_evidence_id=canonical_id,
                    subject_id=subject_id,
                    subject_type=subject_type,
                    source_id=item_source_id,
                    source_categories=list(categories),
                    source_title=str(item.get("source_title", "")).strip(),
                    snippet=str(item.get("snippet", "")).strip(),
                    boundary=boundary,
                    appearances=[],
                    refs=[],
                    structural_classifications=[],
                )
                records_by_key[key] = record
                records.append(record)
            record.appearances.append(appearance)
            record.refs.append(
                {
                    "row": out,
                    "item": item,
                    "build_meta": build_meta,
                    "row_index": row_index,
                    "item_index": item_index,
                    "field_name": str(out.get("field_name", "")).strip(),
                }
            )
        enriched_rows.append(out)
    return enriched_rows, records


def _canonical_evidence_key(
    row: dict[str, Any],
    item: dict[str, Any],
) -> tuple[str, str, str, str, str] | None:
    subject_id = str(row.get("subject_id", "")).strip()
    source_id = _canonical_source_id(row, item)
    snippet = _normalized_canonical_snippet(item)
    if not subject_id or not source_id or not snippet:
        return None
    role_key = _source_section_key(row, item)
    block_index = _canonical_block_index(row, item)
    snippet_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:20]
    return subject_id, source_id, role_key, block_index, snippet_hash


def _canonical_source_id(row: dict[str, Any], item: dict[str, Any]) -> str:
    build_meta = row.get("build_meta") or {}
    source_id = str(build_meta.get("source_id", "")).strip()
    if source_id:
        return source_id
    source_url = str(item.get("source_url", "")).strip()
    if source_url:
        return f"url:{source_url}"
    source_title = str(item.get("source_title", "")).strip()
    if source_title:
        return f"title:{source_title}"
    return ""


def _canonical_evidence_id(key: tuple[str, str, str, str, str]) -> str:
    digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode("utf-8")).hexdigest()[:20]
    return f"canonical-{digest}"


def _normalized_canonical_snippet(item: dict[str, Any]) -> str:
    return " ".join(str(item.get("snippet", "")).casefold().split())


def _source_section_key(row: dict[str, Any], item: dict[str, Any]) -> str:
    build_meta = row.get("build_meta") or {}
    return _role_text(
        item.get("raw_section_role"),
        build_meta.get("raw_section_role"),
        item.get("content_role"),
        build_meta.get("content_role"),
        item.get("section_role"),
        build_meta.get("section_role"),
    ) or "unknown"


def _canonical_block_index(row: dict[str, Any], item: dict[str, Any]) -> str:
    build_meta = row.get("build_meta") or {}
    value = item.get("block_index", build_meta.get("block_index", ""))
    if value is None:
        return ""
    return str(value).strip()


def _canonical_appearance(
    *,
    row: dict[str, Any],
    item: dict[str, Any],
    row_index: int,
    item_index: int,
) -> dict[str, Any]:
    build_meta = row.get("build_meta") or {}
    return {
        "field_name": str(row.get("field_name", "")).strip(),
        "row_index": row_index,
        "item_index": item_index,
        "source_kind": str(build_meta.get("source_kind", "")).strip(),
        "source_title": str(item.get("source_title", "")).strip(),
        "raw_section_role": str(
            item.get("raw_section_role", build_meta.get("raw_section_role", ""))
        ).strip(),
        "section_role": str(item.get("section_role", build_meta.get("section_role", ""))).strip(),
        "content_role": str(item.get("content_role", build_meta.get("content_role", ""))).strip(),
        "auxiliary_role": str(build_meta.get("auxiliary_role", "")).strip(),
        "cluster_id": str(build_meta.get("cluster_id", "")).strip(),
        "quest_node_id": str(build_meta.get("quest_node_id", "")).strip(),
        "faction_id": str(build_meta.get("faction_id", "")).strip(),
        "faction_name": str(build_meta.get("faction_name", "")).strip(),
        "location_id": str(build_meta.get("location_id", "")).strip(),
        "location_name": str(build_meta.get("location_name", "")).strip(),
        "block_index": item.get("block_index", build_meta.get("block_index")),
    }


def _contract_relation_for_item(
    row: dict[str, Any],
    item: dict[str, Any],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    """Return structural relation between an evidence item and the entry-state contract.

    This deliberately uses exact entity labels/IDs already carried by metadata or the contract,
    not lore keywords or substring scans over prose.
    """
    contract = boundary.get("entry_state_contract")
    if not isinstance(contract, dict):
        contract = {}
    field_name = str(row.get("field_name", "")).strip()
    build_meta = row.get("build_meta") or {}
    source_id = _canonical_source_id(row, item)
    candidate_labels, candidate_ids = _contract_candidate_terms(row, item)
    matches: list[dict[str, Any]] = []
    for contract_field in _CONTRACT_MATCH_FIELDS:
        values = contract.get(contract_field)
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            matched_on: list[str] = []
            label = str(entry.get("label", "")).strip()
            if label and _normalize_contract_term(label) in candidate_labels:
                matched_on.append("label")
            for id_key in _CONTRACT_ID_KEYS:
                identifier = str(entry.get(id_key, "")).strip()
                if identifier and _normalize_contract_term(identifier) in candidate_ids:
                    matched_on.append(id_key)
            entry_source_id = str(entry.get("source_id", "")).strip()
            if entry_source_id and entry_source_id == source_id:
                matched_on.append("source_id")
            if not matched_on:
                continue
            matches.append(
                {
                    "contract_field": contract_field,
                    "label": label,
                    "source": str(entry.get("source", "")).strip(),
                    "source_id": entry_source_id,
                    "matched_on": sorted(set(matched_on)),
                    "independent": _contract_match_is_independent(
                        entry,
                        field_name=field_name,
                        source_id=source_id,
                    ),
                }
            )
    matched_labels = sorted(
        {
            str(match.get("label", "")).strip()
            for match in matches
            if str(match.get("label", "")).strip()
        }
    )
    matched_fields = sorted(
        {
            str(match.get("contract_field", "")).strip()
            for match in matches
            if str(match.get("contract_field", "")).strip()
        }
    )
    independent_matches = [match for match in matches if match.get("independent")]
    return {
        "matched": bool(matches),
        "independent_match": bool(independent_matches),
        "matched_fields": matched_fields,
        "matched_labels": matched_labels[:8],
        "match_count": len(matches),
        "independent_match_count": len(independent_matches),
        "candidate_labels": sorted(candidate_labels)[:8],
        "candidate_ids": sorted(candidate_ids)[:8],
        "matches": matches[:8],
        "field_name": field_name,
        "source_id": source_id,
        "source_kind": str(build_meta.get("source_kind", "")).strip(),
    }


def _canonical_contract_relation(record: CanonicalEvidenceRecord) -> dict[str, Any]:
    relations = [
        _contract_relation_for_item(ref["row"], ref["item"], record.boundary)
        for ref in record.refs
    ]
    matched_fields = sorted(
        {
            field
            for relation in relations
            for field in relation.get("matched_fields", [])
            if str(field).strip()
        }
    )
    matched_labels = sorted(
        {
            label
            for relation in relations
            for label in relation.get("matched_labels", [])
            if str(label).strip()
        }
    )
    return {
        "matched": any(relation.get("matched") for relation in relations),
        "independent_match": any(relation.get("independent_match") for relation in relations),
        "matched_fields": matched_fields[:12],
        "matched_labels": matched_labels[:12],
        "appearance_relations": relations[:12],
    }


def _canonical_source_roles(record: CanonicalEvidenceRecord) -> list[str]:
    roles: set[str] = set()
    for appearance in record.appearances:
        for key in ("raw_section_role", "section_role", "content_role", "auxiliary_role"):
            role = str(appearance.get(key, "")).strip()
            if role:
                roles.add(role)
    return sorted(roles)


def _contract_relation_hint(relation: dict[str, Any], *, prefix: str) -> str:
    fields = ",".join(str(field) for field in relation.get("matched_fields", [])[:4])
    independent = "independent" if relation.get("independent_match") else "not_independent"
    if fields:
        return f"{prefix}:{independent}:{fields}"
    return f"{prefix}:{independent}"


def _contract_candidate_terms(row: dict[str, Any], item: dict[str, Any]) -> tuple[set[str], set[str]]:
    build_meta = row.get("build_meta") or {}
    labels: set[str] = set()
    identifiers: set[str] = set()
    for key in (
        "faction_name",
        "location_name",
        "character_name",
        "npc_name",
        "entity_name",
        "instance_name",
    ):
        _add_normalized_contract_term(labels, build_meta.get(key))
    for key in ("source_title", "title", "label", "name"):
        _add_normalized_contract_term(labels, item.get(key))
    for key in (
        "faction_id",
        "location_id",
        "character_id",
        "npc_id",
        "entity_id",
        "cluster_id",
        "quest_node_id",
    ):
        _add_normalized_contract_term(identifiers, build_meta.get(key))
    return labels, identifiers


def _add_normalized_contract_term(target: set[str], value: object) -> None:
    text = _normalize_contract_term(value)
    if text:
        target.add(text)


def _normalize_contract_term(value: object) -> str:
    return " ".join(str(value or "").replace("_", " ").casefold().split())


def _contract_match_is_independent(
    entry: dict[str, Any],
    *,
    field_name: str,
    source_id: str,
) -> bool:
    source = str(entry.get("source", "")).strip()
    entry_source_id = str(entry.get("source_id", "")).strip()
    if field_name in _PROFILE_CONTEXT_FIELD_NAMES:
        if source in {"entry_profile_context", "llm_contract_distillation"}:
            return False
        if entry_source_id and entry_source_id == source_id:
            return False
    return True


def classify_canonical_evidence_record(
    record: CanonicalEvidenceRecord,
    *,
    quest_card_index: dict[str, dict[str, Any]],
) -> TemporalClassification:
    classifications: list[TemporalClassification] = []
    for ref in record.refs:
        classification = classify_evidence_item(
            row=ref["row"],
            item=ref["item"],
            boundary=record.boundary,
            source_categories=record.source_categories,
            quest_card_index=quest_card_index,
        )
        classifications.append(classification)
    record.structural_classifications = classifications
    return _merge_canonical_structural_classifications(record, classifications)


def _merge_canonical_structural_classifications(
    record: CanonicalEvidenceRecord,
    classifications: list[TemporalClassification],
) -> TemporalClassification:
    boundary_id = str(record.boundary.get("boundary_id", "")).strip()
    if not classifications:
        return TemporalClassification(
            AMBIGUOUS_TEMPORAL,
            0.35,
            "canonical_record_without_structural_classifications",
            boundary_id,
            "canonical_unclassified",
            fallback_mode="needs_llm",
        )

    scopes = [classification.scope for classification in classifications]
    if EXCLUDED_NONCANON in scopes:
        return _canonical_scope_from_structural(record, classifications, EXCLUDED_NONCANON)
    if ACTIVE_STORYLINE_OUTCOME in scopes:
        return _canonical_scope_from_structural(
            record, classifications, ACTIVE_STORYLINE_OUTCOME
        )

    has_history_appearance = _canonical_has_field(record, "history_digest")
    has_current_appearance = any(
        appearance.get("field_name") in _CURRENT_FIELD_NAMES
        or appearance.get("field_name") in _PROFILE_CONTEXT_FIELD_NAMES
        for appearance in record.appearances
    )
    unique_scopes = set(scopes)

    if has_history_appearance and has_current_appearance:
        return TemporalClassification(
            AMBIGUOUS_TEMPORAL,
            max(_average_confidence(classifications), 0.55),
            "canonical_history_current_setup_bridge_candidate",
            boundary_id,
            _canonical_structural_hint(classifications, prefix="history_current_bridge_candidate"),
            fallback_mode="needs_llm",
        )

    if unique_scopes == {ENTRY_STATE}:
        return _canonical_scope_from_structural(record, classifications, ENTRY_STATE)
    if unique_scopes == {ACTIVE_STORYLINE}:
        return _canonical_scope_from_structural(record, classifications, ACTIVE_STORYLINE)
    if unique_scopes == {POST_ACTIVE_LORE}:
        return _canonical_scope_from_structural(record, classifications, POST_ACTIVE_LORE)
    if unique_scopes == {AMBIGUOUS_TEMPORAL}:
        return _canonical_ambiguous_from_structural(record, classifications)
    if unique_scopes <= {ENTRY_STATE, ACTIVE_STORYLINE}:
        return _canonical_scope_from_structural(record, classifications, ENTRY_STATE)

    if POST_ACTIVE_LORE in unique_scopes and ENTRY_STATE not in unique_scopes:
        return _canonical_scope_from_structural(record, classifications, POST_ACTIVE_LORE)

    return _canonical_ambiguous_from_structural(record, classifications)


def _canonical_scope_from_structural(
    record: CanonicalEvidenceRecord,
    classifications: list[TemporalClassification],
    scope: str,
) -> TemporalClassification:
    selected = next(
        (classification for classification in classifications if classification.scope == scope),
        classifications[0],
    )
    return TemporalClassification(
        scope,
        max(selected.confidence, _average_confidence(classifications)),
        f"canonical_structural_scope_from_appearances: {selected.reason}",
        selected.boundary_id or str(record.boundary.get("boundary_id", "")),
        _canonical_structural_hint(classifications),
        selected.event_label,
        selected.fallback_mode,
        selected.history_eligibility,
        selected.history_reason,
    )


def _canonical_ambiguous_from_structural(
    record: CanonicalEvidenceRecord,
    classifications: list[TemporalClassification],
) -> TemporalClassification:
    boundary_id = str(record.boundary.get("boundary_id", "")).strip()
    reasons = sorted({classification.reason for classification in classifications if classification.reason})
    return TemporalClassification(
        AMBIGUOUS_TEMPORAL,
        max(_average_confidence(classifications), 0.45),
        "canonical_appearance_conflict_requires_boundary_classification"
        + (f": {'; '.join(reasons)[:220]}" if reasons else ""),
        boundary_id,
        _canonical_structural_hint(classifications, prefix="canonical_conflict"),
        fallback_mode="needs_llm",
    )


def _canonical_structural_hint(
    classifications: list[TemporalClassification],
    *,
    prefix: str = "canonical_structural",
) -> str:
    hints = sorted(
        {
            classification.structural_hint
            for classification in classifications
            if classification.structural_hint
        }
    )
    if not hints:
        return prefix
    return f"{prefix}:{','.join(hints)[:180]}"


def _average_confidence(classifications: list[TemporalClassification]) -> float:
    if not classifications:
        return 0.0
    return sum(classification.confidence for classification in classifications) / len(classifications)


def _canonical_has_field(record: CanonicalEvidenceRecord, field_name: str) -> bool:
    return any(appearance.get("field_name") == field_name for appearance in record.appearances)


def _with_canonical_history_defaults(
    classification: TemporalClassification,
    *,
    appearances: list[dict[str, Any]],
) -> TemporalClassification:
    has_history_appearance = any(
        str(appearance.get("field_name", "")).strip() == "history_digest"
        for appearance in appearances
    )
    eligibility = str(classification.history_eligibility or "").strip()
    reason = str(classification.history_reason or "").strip()
    if not has_history_appearance:
        return replace(
            classification,
            history_eligibility=HISTORY_NOT_APPLICABLE,
            history_reason=reason or "canonical_record_has_no_history_appearance",
        )
    if not eligibility or eligibility not in _HISTORY_ELIGIBILITY_VALUES:
        eligibility, reason = _default_history_eligibility("history_digest", classification.scope)
    else:
        eligibility, reason = _sanitize_history_eligibility(
            "history_digest",
            classification.scope,
            eligibility,
            reason,
        )
    return replace(
        classification,
        history_eligibility=eligibility,
        history_reason=reason,
    )


def _needs_canonical_llm_adjudication(
    classification: TemporalClassification,
    record: CanonicalEvidenceRecord,
) -> bool:
    return bool(record.snippet.strip()) and classification.scope == AMBIGUOUS_TEMPORAL


def _canonical_decision_row(
    record: CanonicalEvidenceRecord,
    classification: TemporalClassification,
    *,
    run_id: str,
) -> dict[str, Any]:
    return {
        "canonical_evidence_id": record.canonical_evidence_id,
        "subject_id": record.subject_id,
        "subject_type": record.subject_type,
        "run_id": run_id or "unknown",
        "source_id": record.source_id,
        "source_title": record.source_title,
        "source_roles": _canonical_source_roles(record),
        "snippet_hash": hashlib.sha256(record.snippet.encode("utf-8")).hexdigest()[:20],
        "snippet": record.snippet[:_PROMPT_SNIPPET_LIMIT],
        "appearance_count": len(record.appearances),
        "appearances": record.appearances,
        "contract_relation": _canonical_contract_relation(record),
        "deterministic_hints": [
            {
                "temporal_scope": classification_row.scope,
                "history_eligibility": classification_row.history_eligibility,
                "confidence": classification_row.confidence,
                "reason": classification_row.reason,
                "structural_hint": classification_row.structural_hint,
                "fallback_mode": classification_row.fallback_mode,
            }
            for classification_row in record.structural_classifications
        ],
        "temporal_scope": classification.scope,
        "temporal_confidence": classification.confidence,
        "temporal_reason": classification.reason,
        "temporal_boundary_id": classification.boundary_id,
        "temporal_structural_hint": classification.structural_hint,
        "temporal_event_label": classification.event_label,
        "temporal_fallback_mode": classification.fallback_mode,
        "history_eligibility": classification.history_eligibility,
        "history_reason": classification.history_reason,
    }


def _with_history_defaults(
    classification: TemporalClassification,
    *,
    field_name: str,
) -> TemporalClassification:
    eligibility = str(classification.history_eligibility or "").strip()
    reason = str(classification.history_reason or "").strip()
    if not eligibility or eligibility not in _HISTORY_ELIGIBILITY_VALUES:
        eligibility, reason = _default_history_eligibility(field_name, classification.scope)
    else:
        eligibility, reason = _sanitize_history_eligibility(
            field_name,
            classification.scope,
            eligibility,
            reason,
        )
    return replace(
        classification,
        history_eligibility=eligibility,
        history_reason=reason,
    )


def _default_history_eligibility(field_name: str, scope: str) -> tuple[str, str]:
    if field_name != "history_digest":
        return HISTORY_NOT_APPLICABLE, "field_not_history_digest"
    if scope == PRE_ENTRY_HISTORY:
        return HISTORY_BACKGROUND, "pre_entry_history_background"
    if scope == ENTRY_STATE:
        return HISTORY_SETUP_BRIDGE, "entry_state_history_setup_bridge"
    if scope == ACTIVE_STORYLINE_OUTCOME:
        return HISTORY_EXCLUDED_OUTCOME, "active_storyline_outcome_excluded_from_history"
    if scope in {POST_ACTIVE_LORE, EXCLUDED_NONCANON, AMBIGUOUS_TEMPORAL}:
        return HISTORY_EXCLUDED_POST_ACTIVE, f"{scope}_excluded_from_history"
    return HISTORY_NOT_APPLICABLE, f"{scope}_not_history_eligible"


def _sanitize_history_eligibility(
    field_name: str,
    scope: str,
    eligibility: str,
    reason: str,
) -> tuple[str, str]:
    if field_name != "history_digest" and eligibility != HISTORY_NOT_APPLICABLE:
        return HISTORY_NOT_APPLICABLE, reason or "field_not_history_digest"
    if scope in {POST_ACTIVE_LORE, EXCLUDED_NONCANON, AMBIGUOUS_TEMPORAL}:
        if eligibility in HISTORY_ELIGIBLE:
            return HISTORY_EXCLUDED_POST_ACTIVE, reason or f"{scope}_excluded_from_history"
    if scope == ACTIVE_STORYLINE_OUTCOME and eligibility in HISTORY_ELIGIBLE:
        return (
            HISTORY_EXCLUDED_OUTCOME,
            reason or "active_storyline_outcome_excluded_from_history",
        )
    if scope == ACTIVE_STORYLINE and eligibility in HISTORY_ELIGIBLE:
        return HISTORY_NOT_APPLICABLE, reason or "active_storyline_not_history_background"
    return eligibility, reason or "llm_history_eligibility"


def build_entry_state_contracts(
    evidence_rows: list[dict[str, Any]],
    *,
    fact_packs_by_entity: dict[str, dict[str, Any]],
    source_snapshots: list[dict[str, Any]],
    questline_card_metadata: dict[str, dict[str, Any]],
    quest_records_by_node: dict[str, dict[str, Any]],
    run_id: str,
) -> tuple[dict[str, EntryStateContract], list[dict[str, Any]]]:
    """Build run-specific entry-state contracts for each generated entity."""
    rows_by_subject: dict[str, list[dict[str, Any]]] = {}
    subject_types: dict[str, str] = {}
    for row in evidence_rows:
        if not isinstance(row, dict):
            continue
        subject_id = str(row.get("subject_id", "")).strip()
        if not subject_id:
            continue
        rows_by_subject.setdefault(subject_id, []).append(row)
        subject_type = str(row.get("subject_type", "")).strip()
        if subject_type:
            subject_types[subject_id] = subject_type

    for entity_id, fact_pack in fact_packs_by_entity.items():
        if not isinstance(fact_pack, dict):
            continue
        entity_type = str(fact_pack.get("entity_type", "")).strip()
        if entity_type:
            subject_types[str(entity_id)] = entity_type
        rows_by_subject.setdefault(str(entity_id), [])

    snapshots_by_entity = _snapshots_by_entity(source_snapshots)
    contracts: dict[str, EntryStateContract] = {}
    decisions: list[dict[str, Any]] = []
    for entity_id in sorted(rows_by_subject):
        entity_type = subject_types.get(entity_id, "")
        fact_pack = fact_packs_by_entity.get(entity_id, {})
        rows = rows_by_subject.get(entity_id, [])
        if entity_type == "zone":
            contract = _build_zone_entry_state_contract(
                entity_id,
                fact_pack,
                rows,
                questline_card_metadata=questline_card_metadata,
                quest_records_by_node=quest_records_by_node,
            )
        elif entity_type == "instance":
            contract = _build_instance_entry_state_contract(
                entity_id,
                fact_pack,
                rows,
                snapshots=snapshots_by_entity.get(entity_id, []),
            )
        else:
            contract = _fallback_entry_state_contract(
                entity_id,
                entity_type,
                rows=rows,
                fact_pack=fact_pack,
            )
        contract.run_id = run_id or "unknown"
        contract = _maybe_distill_entry_state_contract_llm(contract)
        contract.contract_id = _entry_state_contract_id(contract)
        contracts[entity_id] = contract
        decisions.append(contract.to_dict())
    return contracts, decisions


def build_content_boundaries(
    evidence_rows: list[dict[str, Any]],
    *,
    fact_packs_by_entity: dict[str, dict[str, Any]],
    source_snapshots: list[dict[str, Any]],
    questline_card_metadata: dict[str, dict[str, Any]],
    quest_records_by_node: dict[str, dict[str, Any]],
    run_id: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Compatibility projection from entry-state contracts to legacy boundary packets."""
    contracts, _contract_decisions = build_entry_state_contracts(
        evidence_rows,
        fact_packs_by_entity=fact_packs_by_entity,
        source_snapshots=source_snapshots,
        questline_card_metadata=questline_card_metadata,
        quest_records_by_node=quest_records_by_node,
        run_id=run_id,
    )
    return _content_boundaries_from_entry_state_contracts(contracts, run_id=run_id)


def _content_boundaries_from_entry_state_contracts(
    contracts: dict[str, EntryStateContract],
    *,
    run_id: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    boundaries: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    for entity_id in sorted(contracts):
        contract = contracts[entity_id]
        boundary = _content_boundary_from_entry_state_contract(contract)
        boundary["run_id"] = run_id or contract.run_id or "unknown"
        boundary["boundary_id"] = _content_boundary_id(boundary)
        boundaries[entity_id] = boundary
        decisions.append(
            {
                "entity_id": entity_id,
                "entity_type": contract.entity_type,
                "run_id": run_id or contract.run_id or "unknown",
                "boundary_id": boundary["boundary_id"],
                "entry_state_contract_id": contract.contract_id,
                "entry_state_digest": boundary.get("entry_state_digest", ""),
                "anchors": boundary.get("anchors", []),
                "outcome_hints": boundary.get("outcome_hints", []),
                "confidence": boundary.get("confidence", 0.0),
                "reason": boundary.get("reason", ""),
            }
        )
    return boundaries, decisions


def classify_evidence_item(
    *,
    row: dict[str, Any],
    item: dict[str, Any],
    boundary: dict[str, Any],
    source_categories: list[str],
    quest_card_index: dict[str, dict[str, Any]],
) -> TemporalClassification:
    field_name = str(row.get("field_name", "")).strip()
    build_meta = row.get("build_meta") or {}
    raw_role = _role_text(
        item.get("raw_section_role"),
        build_meta.get("raw_section_role"),
        item.get("section_role"),
        build_meta.get("section_role"),
        item.get("content_role"),
        build_meta.get("content_role"),
    )
    snippet = str(item.get("snippet", "")).strip()
    boundary_id = str(boundary.get("boundary_id", "")).strip()

    if _is_excluded_noncanon(raw_role, snippet, source_categories):
        return TemporalClassification(
            EXCLUDED_NONCANON,
            0.95,
            "excluded_by_source_role_or_category",
            boundary_id,
            "excluded_source",
        )

    if field_name in _ACTIVE_FIELD_NAMES:
        return _classify_active_story_item(
            row=row,
            item=item,
            boundary_id=boundary_id,
            quest_card_index=quest_card_index,
        )

    if _is_post_lore_role(raw_role):
        return TemporalClassification(
            POST_ACTIVE_LORE,
            0.88,
            "later_report_or_book_section",
            boundary_id,
            "post_lore_source_role",
        )

    if field_name in _PROFILE_CONTEXT_FIELD_NAMES:
        relation = _contract_relation_for_item(row, item, boundary)
        if relation.get("independent_match"):
            hint = _contract_relation_hint(relation, prefix="profile_context_contract_match")
            if _is_entry_role(raw_role):
                return TemporalClassification(
                    ENTRY_STATE,
                    0.68,
                    "profile_context_tied_to_entry_state_contract",
                    boundary_id,
                    hint,
                )
            return TemporalClassification(
                AMBIGUOUS_TEMPORAL,
                0.52,
                "profile_context_contract_match_requires_boundary_classification",
                boundary_id,
                hint,
                fallback_mode="needs_llm",
            )
        return TemporalClassification(
            AMBIGUOUS_TEMPORAL,
            0.42,
            "profile_context_identity_context_needs_independent_entry_contract",
            boundary_id,
            _contract_relation_hint(relation, prefix="profile_context_no_independent_contract_match"),
            fallback_mode="needs_llm",
        )

    if _is_entry_role(raw_role) or field_name == "boss_pool":
        return TemporalClassification(
            ENTRY_STATE,
            0.86,
            "entry_structural_role",
            boundary_id,
            "entry_section_or_roster",
        )

    if field_name in _CURRENT_FIELD_NAMES:
        if _is_current_field_from_historical_section(raw_role):
            return TemporalClassification(
                AMBIGUOUS_TEMPORAL,
                0.48,
                "current_field_from_historical_section_requires_boundary_classification",
                boundary_id,
                "current_field_historical_section",
                fallback_mode="needs_llm",
            )
        return TemporalClassification(
            ENTRY_STATE,
            0.7,
            "current_field_boundary_context",
            boundary_id,
            "current_field",
        )

    if field_name == "history_digest":
        return TemporalClassification(
            AMBIGUOUS_TEMPORAL,
            0.45,
            "history_digest_requires_boundary_classification",
            boundary_id,
            "history_digest",
            fallback_mode="needs_llm",
        )

    return TemporalClassification(
        AMBIGUOUS_TEMPORAL,
        0.4,
        "unclassified_source_role_requires_boundary_classification",
        boundary_id,
        "unclassified_source_role",
        fallback_mode="needs_llm",
    )


def adjudicate_canonical_temporal_classifications_llm(
    records: list[CanonicalEvidenceRecord],
) -> dict[str, TemporalClassification]:
    """Batch LLM adjudication for canonical source paragraphs."""
    overrides: dict[str, TemporalClassification] = {}
    for group in _canonical_llm_groups(records):
        record_by_id = {
            record.canonical_evidence_id: record
            for record in group
            if record.classification is not None
        }
        if not record_by_id:
            continue
        result: dict[str, Any]
        try:
            result = llm_json_with_retry(
                required_keys=("classifications",),
                response_json_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["classifications"],
                    "properties": {
                        "classifications": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "canonical_evidence_id",
                                    "temporal_scope",
                                    "history_eligibility",
                                    "rationale",
                                    "history_rationale",
                                    "event_label",
                                ],
                                "properties": {
                                    "canonical_evidence_id": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "temporal_scope": {
                                        "type": "string",
                                        "enum": list(_TEMPORAL_SCOPE_VALUES),
                                    },
                                    "history_eligibility": {
                                        "type": "string",
                                        "enum": list(_HISTORY_ELIGIBILITY_VALUES),
                                    },
                                    "rationale": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 260,
                                    },
                                    "history_rationale": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 260,
                                    },
                                    "event_label": {"type": "string", "maxLength": 120},
                                },
                            },
                        }
                    },
                },
                system_prompt=_temporal_adjudication_system_prompt(
                    canonical=True,
                ),
                user_prompt=_canonical_temporal_adjudication_prompt(group),
                response_schema_name="wiki_first_temporal_boundary_classification",
                substep="wiki_first_temporal_boundary_classification",
                max_attempts=2,
            )
        except Exception as exc:  # pragma: no cover - provider failures keep fallback labels
            for record in group:
                prior = record.classification
                if prior is None:
                    continue
                overrides[record.canonical_evidence_id] = TemporalClassification(
                    prior.scope,
                    prior.confidence,
                    f"{prior.reason}; llm_boundary_classification_failed={exc.__class__.__name__}",
                    prior.boundary_id,
                    prior.structural_hint,
                    prior.event_label,
                    "llm_failed",
                    prior.history_eligibility,
                    prior.history_reason,
                )
            continue

        rows = result.get("classifications", [])
        if not isinstance(rows, list):
            continue
        for row_result in rows:
            if not isinstance(row_result, dict):
                continue
            canonical_id = str(row_result.get("canonical_evidence_id", "")).strip()
            record = record_by_id.get(canonical_id)
            if record is None or record.classification is None:
                continue
            prior = record.classification
            scope = str(row_result.get("temporal_scope", "")).strip()
            if scope not in TEMPORAL_SCOPES:
                continue
            history_eligibility = str(row_result.get("history_eligibility", "")).strip()
            if history_eligibility not in _HISTORY_ELIGIBILITY_VALUES:
                history_eligibility = HISTORY_NOT_APPLICABLE
            rationale = str(row_result.get("rationale", "")).strip()
            history_rationale = str(row_result.get("history_rationale", "")).strip()
            event_label = str(row_result.get("event_label", "")).strip()
            overrides[canonical_id] = TemporalClassification(
                scope,
                0.84 if scope != AMBIGUOUS_TEMPORAL else max(prior.confidence, 0.5),
                f"llm_boundary_classified_from_{prior.reason}: {rationale[:260]}",
                prior.boundary_id,
                prior.structural_hint,
                event_label,
                "llm_boundary",
                history_eligibility,
                history_rationale[:260],
            )
    return overrides


def _canonical_llm_groups(
    records: list[CanonicalEvidenceRecord],
    *,
    max_group_size: int = 12,
) -> list[list[CanonicalEvidenceRecord]]:
    grouped: dict[tuple[str, str], list[CanonicalEvidenceRecord]] = {}
    for record in records:
        grouped.setdefault((record.subject_id, record.source_id), []).append(record)
    chunks: list[list[CanonicalEvidenceRecord]] = []
    for group in grouped.values():
        for index in range(0, len(group), max_group_size):
            chunks.append(group[index : index + max_group_size])
    return chunks


def _canonical_temporal_adjudication_prompt(records: list[CanonicalEvidenceRecord]) -> str:
    first = records[0]
    payload = {
        "page_type": first.subject_type or "unknown",
        "subject_id": first.subject_id,
        "source_id": first.source_id,
        "page_categories": first.source_categories[:20],
        "active_content_boundary": _boundary_prompt_payload(first.boundary),
        "items": [_canonical_prompt_item(record) for record in records],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


def _canonical_prompt_item(record: CanonicalEvidenceRecord) -> dict[str, Any]:
    classification = record.classification or TemporalClassification(
        AMBIGUOUS_TEMPORAL,
        0.0,
        "missing_prior_classification",
    )
    return {
        "canonical_evidence_id": record.canonical_evidence_id,
        "candidate_temporal_scope": classification.scope,
        "candidate_history_eligibility": classification.history_eligibility,
        "candidate_reason": classification.reason,
        "source_title": record.source_title,
        "source_roles": _canonical_source_roles(record),
        "snippet": record.snippet[:_PROMPT_SNIPPET_LIMIT],
        "appearances": record.appearances[:12],
        "appearance_field_names": sorted(
            {
                str(appearance.get("field_name", "")).strip()
                for appearance in record.appearances
                if str(appearance.get("field_name", "")).strip()
            }
        ),
        "contract_relation": _canonical_contract_relation(record),
        "deterministic_labels": [
            {
                "temporal_scope": classification_row.scope,
                "history_eligibility": classification_row.history_eligibility,
                "reason": classification_row.reason,
                "structural_hint": classification_row.structural_hint,
            }
            for classification_row in record.structural_classifications
        ],
    }


def _temporal_adjudication_system_prompt(*, canonical: bool = False) -> str:
    prefix = ""
    if canonical:
        prefix = (
            "Each input item is one canonical source paragraph. It may have multiple "
            "routed appearances in history, current/overview, quest, faction, location, or "
            "instance pools. Classify the paragraph once using all appearances together; "
            "do not return different labels for different drafted fields.\n\n"
        )
    return (
        prefix
        + "Classify World of Warcraft lore evidence by how each paragraph relates to what "
        "the player is walking into on the current zone or instance page. Do not sort by "
        "expansion chronology or named-era keywords. Use the structured entry-state "
        "contract inside the active-content boundary as the primary current-state context; "
        "then use source structure, quest/roster linkage, and the paragraph text.\n\n"
        "The key question is not 'which expansion or named era is later?' It is whether the "
        "paragraph is before, part of, an outcome of, or after/outside the playable entry "
        "state described by the contract. A paragraph can happen long after an origin story, "
        "fall, founding, or first invasion and still be pre_entry_history if it is background "
        "for the contract's current state. Paragraphs mentioning heroes, adventurers, orders, "
        "campaigns, or wars are not post_active_lore by that fact alone.\n\n"
        "Labels:\n"
        "- pre_entry_history: background that happened before the player enters this content.\n"
        "- entry_state: the current setup visible or true as the player arrives.\n"
        "- active_storyline: events the player is about to participate in, without outcome.\n"
        "- active_storyline_outcome: results, resolutions, deaths, victories, or late-chain reveals.\n"
        "- post_active_lore: later off-screen lore, reports, books, or events after this content. "
        "For instances, do not label a paragraph pre_entry_history merely because it happens "
        "before the player personally enters. pre_entry_history is origin/fall/background that "
        "establishes the current playable state. Separate later visitors, outside factions, "
        "reports, retrieval missions, research missions, or objectives absent from the current "
        "roster/setup anchors are post_active_lore unless they directly establish the dungeon's "
        "current entry state.\n"
        "- excluded_noncanon: RPG-only, removed, speculative, or non-retail/non-canon material.\n"
        "- ambiguous_temporal: still unclear relative to the entry boundary.\n\n"
        "Profile/context pages need extra caution. Faction, character, location, parent, "
        "related-lore, and instance-lore profile paragraphs are identity context unless "
        "the contract_relation shows an independent entry-state match or local source "
        "structure ties them to this page's current setup. Do not classify generic profile "
        "history as entry_state just because the profile page itself was fetched. If a "
        "contract-tied profile paragraph describes older background for why that current "
        "entity matters, prefer pre_entry_history or history_setup_bridge over a forced "
        "entry_state label.\n\n"
        "History eligibility labels:\n"
        "- history_background: origin, fall, or background that belongs in a history card.\n"
        "- history_setup_bridge: a transition/setup paragraph that explains the current "
        "playable state, current occupants, ruler, threat, holdout, or condition as the "
        "player enters. Use this even if the paragraph also describes the current setup.\n"
        "- history_excluded_outcome: active quest or dungeon outcome, boss defeat, player "
        "resolution, late-chain reveal, victory, or death.\n"
        "- history_excluded_post_active: later off-screen visitors, reports, book/retrieval "
        "missions, research missions, or outside-faction activity absent from the current "
        "setup anchors.\n"
        "- history_not_applicable: not a history/background paragraph.\n\n"
        "Do not treat every later paragraph as post-active. If it explains why the current "
        "roster, controlling faction, ruler, major threat, or site condition exists when "
        "the player arrives, classify it as entry_state with history_setup_bridge. For "
        "zones, this includes transition paragraphs that explain current quest hubs, "
        "restoration efforts, faction bases, staging grounds, or front lines the player "
        "encounters on entry. Do not use history_setup_bridge for player-completed quest "
        "outcomes, control changes caused by the active storyline, victory summaries, or "
        "later off-screen reports. Return one temporal_scope and one history_eligibility "
        "per item, with short rationales grounded only in the inputs."
    )


def _llm_temporal_adjudication_disabled() -> bool:
    settings = load_ai_settings()
    if not settings.openai_ready:
        return True
    return os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}


def _classify_active_story_item(
    *,
    row: dict[str, Any],
    item: dict[str, Any],
    boundary_id: str,
    quest_card_index: dict[str, dict[str, Any]],
) -> TemporalClassification:
    build_meta = row.get("build_meta") or {}
    cluster_id = str(build_meta.get("cluster_id", "")).strip()
    quest_node_id = str(build_meta.get("quest_node_id", "")).strip()
    meta = quest_card_index.get(cluster_id, {})
    chain_refs = [str(ref) for ref in meta.get("chain_refs", []) if str(ref).strip()]
    overflow_refs = {str(ref) for ref in meta.get("overflow_refs", []) if str(ref).strip()}
    if quest_node_id and chain_refs:
        try:
            position = chain_refs.index(quest_node_id)
        except ValueError:
            position = -1
        if 0 <= position < _SETUP_QUEST_LIMIT:
            return TemporalClassification(
                ENTRY_STATE,
                0.92,
                "questline_start_anchor",
                boundary_id,
                "early_quest_record",
            )
        if quest_node_id in overflow_refs or position >= max(0, len(chain_refs) - _OUTCOME_QUEST_LIMIT):
            return TemporalClassification(
                ACTIVE_STORYLINE_OUTCOME,
                0.84,
                "late_or_overflow_questline_member",
                boundary_id,
                "late_quest_record",
            )
    return TemporalClassification(
        ACTIVE_STORYLINE,
        0.76,
        "active_quest_or_storyline_evidence",
        boundary_id,
        "active_quest_record",
    )


def _build_zone_entry_state_contract(
    entity_id: str,
    fact_pack: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    questline_card_metadata: dict[str, dict[str, Any]],
    quest_records_by_node: dict[str, dict[str, Any]],
) -> EntryStateContract:
    name = str(fact_pack.get("name") or fact_pack.get("entity_id") or entity_id)
    contract = EntryStateContract(
        entity_id=entity_id,
        entity_type="zone",
        name=name,
    )
    for cluster_id, card in sorted(questline_card_metadata.items()):
        if not isinstance(card, dict):
            continue
        if str(card.get("zone_id", "")).strip() != entity_id:
            continue
        chain_refs = [
            str(ref)
            for ref in card.get("registry_chain_refs") or card.get("chain_refs") or []
            if str(ref).strip()
        ]
        overflow_refs = [str(ref) for ref in card.get("overflow_chain_refs") or [] if str(ref).strip()]
        setup_refs = _first_nonempty_quest_refs(
            chain_refs,
            quest_records_by_node,
            limit=_SETUP_QUEST_LIMIT,
        )
        late_refs = _late_quest_refs(chain_refs, overflow_refs)
        setup_snippets = [
            _quest_record_summary(quest_records_by_node.get(ref, {})) for ref in setup_refs
        ]
        setup_snippets = [_truncate(snippet, _BOUNDARY_SNIPPET_LIMIT) for snippet in setup_snippets if snippet]
        late_snippets = [
            _quest_record_summary(quest_records_by_node.get(ref, {})) for ref in late_refs
        ]
        late_snippets = [_truncate(snippet, _BOUNDARY_SNIPPET_LIMIT) for snippet in late_snippets if snippet]
        title = str(
            card.get("display_title")
            or card.get("title")
            or card.get("start_anchor")
            or cluster_id
        ).strip()
        faction = str(card.get("faction") or card.get("majority_faction") or "").strip()
        anchor = {
            "kind": "questline_setup",
            "cluster_id": str(cluster_id),
            "card_id": str(card.get("card_id", "")).strip(),
            "title": title,
            "faction": faction,
            "start_anchor": str(card.get("start_anchor", "")).strip(),
            "setup_quest_refs": setup_refs,
            "setup_snippets": setup_snippets,
            "setup_npcs": _quest_record_people(setup_refs, quest_records_by_node),
        }
        if title or setup_snippets:
            contract.source_anchor_refs.append(anchor)
            _append_contract_entry(
                contract.active_storylines,
                title,
                source="questline_card_metadata",
                cluster_id=str(cluster_id),
                faction=faction,
            )
            _append_contract_entry(
                contract.active_conflicts,
                title,
                source="questline_card_metadata",
                cluster_id=str(cluster_id),
                faction=faction,
            )
        if faction and faction.casefold() not in {"shared", "neutral"}:
            _append_contract_entry(
                contract.current_factions,
                faction,
                source="questline_card_metadata",
                cluster_id=str(cluster_id),
            )
        for ref, snippet in zip(setup_refs, setup_snippets, strict=False):
            _append_contract_entry(
                contract.current_objectives,
                _quest_record_title(quest_records_by_node.get(ref, {})) or ref,
                source="early_quest_record",
                quest_ref=ref,
                cluster_id=str(cluster_id),
                snippet=snippet,
            )
        if title and (late_refs or late_snippets):
            contract.excluded_outcome_hints.append(
                {
                    "kind": "questline_outcome_reference",
                    "cluster_id": str(cluster_id),
                    "title": title,
                    "late_or_overflow_quest_refs": late_refs,
                    "outcome_snippets": late_snippets[:_OUTCOME_QUEST_LIMIT],
                }
            )

    current_context_anchors = _supplemental_current_state_anchors(
        rows,
        kind="zone_current_structural_context",
    )[:3]
    _add_profile_context_entities_from_rows(contract, rows)
    fallback_anchors: list[dict[str, Any]] = []
    if not contract.source_anchor_refs:
        fallback_anchors = _fallback_current_anchors(rows, kind="zone_current_setup")
        contract.source_anchor_refs.extend(current_context_anchors or fallback_anchors)
        contract.reason = "fallback_current_structural_evidence"
        contract.confidence = 0.45 if contract.source_anchor_refs else 0.25
    else:
        contract.source_anchor_refs.extend(current_context_anchors)
        contract.reason = (
            "questline_card_setup_records_with_current_context"
            if current_context_anchors
            else "questline_card_setup_records"
        )
        contract.confidence = 0.9
    _add_anchor_snippets_as_current_objectives(contract, current_context_anchors or fallback_anchors)
    return contract


def _build_instance_entry_state_contract(
    entity_id: str,
    fact_pack: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    snapshots: list[dict[str, Any]],
) -> EntryStateContract:
    name = str(fact_pack.get("name") or fact_pack.get("entity_id") or entity_id)
    primary = _primary_snapshot(snapshots)
    infobox = primary.get("infobox") if isinstance(primary.get("infobox"), dict) else {}
    structured_links = primary.get("structured_links") if isinstance(primary.get("structured_links"), list) else []
    roster_labels: list[str] = []
    for key in ("Bosses", "End boss", "bosses", "end boss", "End Boss"):
        value = infobox.get(key) if isinstance(infobox, dict) else None
        if value:
            roster_labels.append(str(value).strip())
    for link in structured_links:
        if not isinstance(link, dict):
            continue
        role = _role_text(link.get("section_role"), link.get("parent_section_role"))
        if _is_entry_role(role):
            label = str(link.get("label", "")).strip()
            if label and label not in roster_labels:
                roster_labels.append(label)
        if len(roster_labels) >= 16:
            break

    contract = EntryStateContract(
        entity_id=entity_id,
        entity_type="instance",
        name=name,
    )
    for label in _infobox_values(infobox, "Location", "Location(s)", "location"):
        _append_contract_entry(contract.current_locations, label, source="instance_infobox")
    for label in _infobox_values(infobox, "Race(s)", "Faction", "Factions", "race(s)"):
        _append_contract_entry(contract.current_factions, label, source="instance_infobox")
    for label in _infobox_values(
        infobox,
        "Controlled by",
        "Controller",
        "Leader",
        "End boss",
        "End Boss",
    ):
        _append_contract_entry(contract.current_controller, label, source="instance_infobox")
    for label in roster_labels[:16]:
        _append_contract_entry(contract.current_inhabitants, label, source="current_roster")
        _append_contract_entry(contract.active_encounters, label, source="current_roster")

    if infobox or roster_labels:
        contract.source_anchor_refs.append(
            {
                "kind": "instance_current_structure",
                "title": name,
                "infobox_summary": _summarize_infobox(infobox),
                "roster_labels": roster_labels[:16],
            }
        )
    supplemental_anchors = _supplemental_current_state_anchors(
        rows,
        kind="instance_current_structural_context",
    )[:3]
    contract.source_anchor_refs.extend(supplemental_anchors)
    _add_profile_context_entities_from_rows(contract, rows)
    _add_anchor_snippets_as_current_objectives(contract, supplemental_anchors)
    contract.reason = (
        "instance_infobox_roster_and_current_evidence"
        if contract.source_anchor_refs
        else "fallback_empty_boundary"
    )
    contract.confidence = 0.86 if infobox or roster_labels else (0.45 if contract.source_anchor_refs else 0.25)
    return contract


def _fallback_entry_state_contract(
    entity_id: str,
    entity_type: object = "",
    *,
    rows: list[dict[str, Any]] | None = None,
    fact_pack: dict[str, Any] | None = None,
) -> EntryStateContract:
    anchors = _fallback_current_anchors(rows or [], kind="current_setup_fallback")
    name = str((fact_pack or {}).get("name") or entity_id)
    contract = EntryStateContract(
        entity_id=entity_id,
        entity_type=str(entity_type or (fact_pack or {}).get("entity_type", "")),
        name=name,
        source_anchor_refs=anchors,
        confidence=0.35 if anchors else 0.2,
        reason="fallback_current_structural_evidence" if anchors else "missing_boundary_evidence",
    )
    _add_anchor_snippets_as_current_objectives(contract, anchors)
    return contract


def _content_boundary_from_entry_state_contract(contract: EntryStateContract) -> dict[str, Any]:
    contract_payload = contract.to_dict()
    return {
        "entity_id": contract.entity_id,
        "entity_type": contract.entity_type,
        "name": contract.name,
        "entry_state_contract_id": contract.contract_id,
        "entry_state_contract": contract_payload,
        "entry_state_digest": _entry_state_contract_digest(contract),
        "anchors": contract.source_anchor_refs,
        "outcome_hints": contract.excluded_outcome_hints,
        "confidence": contract.confidence,
        "reason": f"entry_state_contract:{contract.reason}",
    }


def _fallback_boundary(
    entity_id: str,
    entity_type: object = "",
    *,
    rows: list[dict[str, Any]] | None = None,
    fact_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = _fallback_entry_state_contract(
        entity_id,
        entity_type,
        rows=rows or [],
        fact_pack=fact_pack or {},
    )
    contract.contract_id = _entry_state_contract_id(contract)
    boundary = _content_boundary_from_entry_state_contract(contract)
    boundary["boundary_id"] = _content_boundary_id(boundary)
    return boundary


def _supplemental_current_state_anchors(
    rows: list[dict[str, Any]],
    *,
    kind: str,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    eligible_fields = _CURRENT_FIELD_NAMES | _PROFILE_CONTEXT_FIELD_NAMES
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name", "")).strip()
        if field_name not in eligible_fields:
            continue
        items = row.get("evidence_items")
        if not isinstance(items, list):
            continue
        snippets: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_role = _role_text(
                item.get("raw_section_role"),
                (row.get("build_meta") or {}).get("raw_section_role"),
                item.get("content_role"),
                (row.get("build_meta") or {}).get("content_role"),
            )
            if field_name in _PROFILE_CONTEXT_FIELD_NAMES and raw_role and not _is_entry_role(raw_role):
                continue
            snippet = str(item.get("snippet", "")).strip()
            if snippet:
                snippets.append(_truncate(snippet, _BOUNDARY_SNIPPET_LIMIT))
            if len(snippets) >= 2:
                break
        if snippets:
            anchors.append(
                {
                    "kind": kind,
                    "field_name": field_name,
                    "source_id": str((row.get("build_meta") or {}).get("source_id", "")).strip(),
                    "setup_snippets": snippets,
                }
            )
        if len(anchors) >= 6:
            break
    return anchors


def _fallback_current_anchors(rows: list[dict[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name", "")).strip()
        if field_name not in _CURRENT_FIELD_NAMES and field_name not in _ACTIVE_FIELD_NAMES:
            continue
        items = row.get("evidence_items")
        if not isinstance(items, list):
            continue
        snippets: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = str(item.get("snippet", "")).strip()
            if snippet:
                snippets.append(_truncate(snippet, _BOUNDARY_SNIPPET_LIMIT))
            if len(snippets) >= 2:
                break
        if snippets:
            anchors.append(
                {
                    "kind": kind,
                    "field_name": field_name,
                    "source_id": str((row.get("build_meta") or {}).get("source_id", "")).strip(),
                    "setup_snippets": snippets,
                }
            )
        if len(anchors) >= 6:
            break
    return anchors


def _snapshot_categories_by_source(snapshots: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        source_id = str(snapshot.get("source_id", "")).strip()
        categories = snapshot.get("categories")
        if source_id and isinstance(categories, list):
            result[source_id] = [str(category) for category in categories if str(category).strip()]
    return result


def _snapshots_by_entity(snapshots: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        entity_id = str(snapshot.get("entity_id", "")).strip()
        if entity_id:
            result.setdefault(entity_id, []).append(snapshot)
    return result


def _primary_snapshot(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    for snapshot in snapshots:
        if not str(snapshot.get("auxiliary_role", "")).strip():
            return snapshot
    return snapshots[0] if snapshots else {}


def _quest_card_index(metadata: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for cluster_id, row in metadata.items():
        if not isinstance(row, dict):
            continue
        result[str(cluster_id)] = {
            "chain_refs": list(row.get("registry_chain_refs") or row.get("chain_refs") or []),
            "overflow_refs": list(row.get("overflow_chain_refs") or []),
        }
    return result


def _first_nonempty_quest_refs(
    chain_refs: list[str],
    quest_records_by_node: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    refs: list[str] = []
    for ref in chain_refs:
        if _quest_record_summary(quest_records_by_node.get(ref, {})):
            refs.append(ref)
        if len(refs) >= limit:
            break
    return refs


def _late_quest_refs(chain_refs: list[str], overflow_refs: list[str]) -> list[str]:
    refs: list[str] = []
    for ref in overflow_refs:
        if ref and ref not in refs:
            refs.append(ref)
    for ref in chain_refs[-_OUTCOME_QUEST_LIMIT:]:
        if ref and ref not in refs:
            refs.append(ref)
    return refs[: max(_OUTCOME_QUEST_LIMIT, len(overflow_refs))]


def _quest_record_summary(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    fields = (
        record.get("description"),
        record.get("quest_description"),
        record.get("objectives_text"),
        record.get("summary"),
        record.get("title"),
    )
    return " ".join(str(value).strip() for value in fields if str(value or "").strip())


def _quest_record_title(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    return str(record.get("title") or record.get("name") or record.get("node_id") or "").strip()


def _quest_record_people(
    quest_refs: list[str],
    quest_records_by_node: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ref in quest_refs:
        record = quest_records_by_node.get(ref, {})
        if not isinstance(record, dict):
            continue
        for role, key in (("start_npc", "start_npc"), ("end_npc", "end_npc")):
            label = str(record.get(key, "")).strip()
            if not label:
                continue
            dedupe_key = (role, label.casefold())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            people.append({"role": role, "label": label, "quest_ref": ref})
    return people


def _append_contract_entry(
    target: list[dict[str, Any]],
    label: object,
    *,
    source: str,
    **metadata: Any,
) -> None:
    text = _truncate(str(label or "").strip(), 220)
    if not text:
        return
    if any(str(row.get("label", "")).casefold() == text.casefold() for row in target):
        return
    row: dict[str, Any] = {"label": text, "source": source}
    for key, value in metadata.items():
        if value in ("", None, [], {}):
            continue
        row[key] = value
    target.append(row)


def _add_anchor_snippets_as_current_objectives(
    contract: EntryStateContract,
    anchors: list[dict[str, Any]],
) -> None:
    for anchor in anchors:
        snippets = anchor.get("setup_snippets")
        if not isinstance(snippets, list):
            continue
        label = str(anchor.get("title") or anchor.get("field_name") or anchor.get("kind") or "").strip()
        for index, snippet in enumerate(snippets):
            if not str(snippet).strip():
                continue
            _append_contract_entry(
                contract.current_objectives,
                label or f"current_setup_{index + 1}",
                source=str(anchor.get("kind", "current_structural_context")),
                source_id=str(anchor.get("source_id", "")).strip(),
                snippet=_truncate(str(snippet), _BOUNDARY_SNIPPET_LIMIT),
            )


def _add_profile_context_entities_from_rows(
    contract: EntryStateContract,
    rows: list[dict[str, Any]],
) -> None:
    """Copy explicit profile target metadata into contract fields when structurally current."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name", "")).strip()
        if field_name not in {"location_pool", "faction_pool"}:
            continue
        build_meta = row.get("build_meta") or {}
        if not isinstance(build_meta, dict):
            continue
        if not _row_has_entry_context(row):
            continue
        if field_name == "location_pool":
            label = str(build_meta.get("location_name", "")).strip()
            identifier = str(build_meta.get("location_id", "")).strip()
            _append_contract_entry(
                contract.current_locations,
                label,
                source="entry_profile_context",
                location_id=identifier,
                source_id=str(build_meta.get("source_id", "")).strip(),
            )
        elif field_name == "faction_pool":
            label = str(build_meta.get("faction_name", "")).strip()
            identifier = str(build_meta.get("faction_id", "")).strip()
            _append_contract_entry(
                contract.current_factions,
                label,
                source="entry_profile_context",
                faction_id=identifier,
                source_id=str(build_meta.get("source_id", "")).strip(),
            )


def _row_has_entry_context(row: dict[str, Any]) -> bool:
    build_meta = row.get("build_meta") or {}
    items = row.get("evidence_items")
    roles = [
        _role_text(
            build_meta.get("raw_section_role"),
            build_meta.get("section_role"),
            build_meta.get("content_role"),
        )
    ]
    if isinstance(items, list):
        for item in items[:4]:
            if isinstance(item, dict):
                roles.append(
                    _role_text(
                        item.get("raw_section_role"),
                        item.get("section_role"),
                        item.get("content_role"),
                    )
                )
    return any(_is_entry_role(role) for role in roles if role)


def _infobox_values(infobox: dict[str, Any], *keys: str) -> list[str]:
    if not isinstance(infobox, dict):
        return []
    values: list[str] = []
    for key in keys:
        value = infobox.get(key)
        if isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item).strip())
        elif str(value or "").strip():
            values.append(str(value).strip())
    return values


def _entry_state_contract_digest(contract: EntryStateContract) -> str:
    anchor_digest = _boundary_digest(contract.source_anchor_refs)
    if anchor_digest:
        return anchor_digest
    parts: list[str] = []
    for entries in (
        contract.active_storylines,
        contract.active_conflicts,
        contract.current_locations,
        contract.current_factions,
        contract.current_inhabitants,
        contract.current_controller,
        contract.active_encounters,
        contract.current_objectives,
    ):
        for entry in entries:
            label = str(entry.get("label", "")).strip()
            if label:
                parts.append(label)
            if len(parts) >= 24:
                break
        if len(parts) >= 24:
            break
    return _truncate(" | ".join(parts), _BOUNDARY_DIGEST_LIMIT)


def _entry_state_contract_id(contract: EntryStateContract) -> str:
    payload = {
        key: value
        for key, value in contract.to_dict().items()
        if key not in {"contract_id", "run_id"}
    }
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    entity_id = contract.entity_id or "entity"
    return f"entry-state-{entity_id}-{digest}"


def _maybe_distill_entry_state_contract_llm(contract: EntryStateContract) -> EntryStateContract:
    if not _entry_state_contract_distillation_enabled():
        return contract
    field_names = [
        "current_locations",
        "current_factions",
        "current_threats",
        "active_conflicts",
        "current_objectives",
        "active_storylines",
        "current_inhabitants",
        "current_controller",
        "active_encounters",
    ]
    try:
        result = llm_json_with_retry(
            required_keys=("contract_fields",),
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["contract_fields"],
                "properties": {
                    "contract_fields": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": field_names,
                        "properties": {
                            field_name: {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 120},
                                "maxItems": 24,
                            }
                            for field_name in field_names
                        },
                    }
                },
            },
            system_prompt=(
                "Distill the deterministic entry-state contract into concise labels. "
                "Use only entities, factions, objectives, locations, inhabitants, or "
                "encounters already present in the input contract. Do not infer chronology, "
                "do not add outside lore, and do not invent names."
            ),
            user_prompt=json.dumps({"deterministic_contract": contract.to_dict()}, ensure_ascii=True),
            response_schema_name="wiki_first_entry_state_contract_distillation",
            substep="wiki_first_entry_state_contract_distillation",
            max_attempts=2,
        )
    except Exception:
        return contract
    fields = result.get("contract_fields")
    if not isinstance(fields, dict):
        return contract
    allowed_text = json.dumps(contract.to_dict(), ensure_ascii=True).casefold()
    for field_name in field_names:
        target = getattr(contract, field_name, None)
        labels = fields.get(field_name)
        if not isinstance(target, list) or not isinstance(labels, list):
            continue
        for label in labels:
            text = str(label).strip()
            if _distilled_contract_label_allowed(text, allowed_text):
                _append_contract_entry(target, text, source="llm_contract_distillation")
    contract.reason = f"{contract.reason}; optional_llm_contract_distilled"
    return contract


def _distilled_contract_label_allowed(label: str, allowed_text: str) -> bool:
    text = " ".join(str(label or "").split())
    if len(text) < 3:
        return False
    return text.casefold() in allowed_text


def _entry_state_contract_distillation_enabled() -> bool:
    enabled = os.environ.get("WOW_LORE_ENTRY_STATE_CONTRACT_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return enabled and not _llm_temporal_adjudication_disabled()


def _summarize_infobox(infobox: dict[str, Any]) -> dict[str, str]:
    if not isinstance(infobox, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in infobox.items():
        if len(result) >= 10:
            break
        text = str(value).strip()
        if text:
            result[str(key)] = _truncate(text, 180)
    return result


def _boundary_digest(anchors: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for anchor in anchors:
        title = str(anchor.get("title") or anchor.get("field_name") or anchor.get("kind") or "").strip()
        faction = str(anchor.get("faction", "")).strip()
        snippets = anchor.get("setup_snippets")
        if not isinstance(snippets, list):
            snippets = []
        roster = anchor.get("roster_labels")
        if not isinstance(roster, list):
            roster = []
        text_parts = [title]
        if faction:
            text_parts.append(faction)
        text_parts.extend(str(snippet).strip() for snippet in snippets if str(snippet).strip())
        if roster:
            text_parts.append("Roster: " + ", ".join(str(label) for label in roster[:8]))
        line = " | ".join(part for part in text_parts if part)
        if line:
            parts.append(line)
    return _truncate(" ".join(parts), _BOUNDARY_DIGEST_LIMIT)


def _content_boundary_id(boundary: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in boundary.items()
        if key not in {"boundary_id", "run_id"}
    }
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    entity_id = str(boundary.get("entity_id", "entity")).strip() or "entity"
    return f"boundary-{entity_id}-{digest}"


def _boundary_prompt_payload(boundary: dict[str, Any]) -> dict[str, Any]:
    anchors = boundary.get("anchors")
    outcome_hints = boundary.get("outcome_hints")
    contract = boundary.get("entry_state_contract")
    if not isinstance(anchors, list):
        anchors = []
    if not isinstance(outcome_hints, list):
        outcome_hints = []
    if not isinstance(contract, dict):
        contract = {}
    return {
        "boundary_id": str(boundary.get("boundary_id", "")),
        "entity_id": str(boundary.get("entity_id", "")),
        "entity_type": str(boundary.get("entity_type", "")),
        "name": str(boundary.get("name", "")),
        "entry_state_contract_id": str(boundary.get("entry_state_contract_id", "")),
        "entry_state_contract": _entry_state_contract_prompt_payload(contract),
        "entry_state_digest": _truncate(
            str(boundary.get("entry_state_digest", "")),
            _BOUNDARY_DIGEST_LIMIT,
        ),
        "setup_anchors": anchors[:8],
        "outcome_hints": outcome_hints[:8],
        "confidence": boundary.get("confidence", 0.0),
        "reason": str(boundary.get("reason", "")),
    }


def _entry_state_contract_prompt_payload(contract: dict[str, Any]) -> dict[str, Any]:
    field_names = (
        "current_locations",
        "current_factions",
        "current_threats",
        "active_conflicts",
        "current_objectives",
        "active_storylines",
        "current_inhabitants",
        "current_controller",
        "active_encounters",
        "excluded_outcome_hints",
        "source_anchor_refs",
    )
    payload = {
        "contract_id": str(contract.get("contract_id", "")),
        "entity_id": str(contract.get("entity_id", "")),
        "entity_type": str(contract.get("entity_type", "")),
        "name": str(contract.get("name", "")),
        "confidence": contract.get("confidence", 0.0),
        "reason": str(contract.get("reason", "")),
    }
    for field_name in field_names:
        values = contract.get(field_name)
        if not isinstance(values, list):
            values = []
        payload[field_name] = values[:8]
    return payload


def _role_text(*values: object) -> str:
    return " ".join(str(value or "").replace("_", " ").casefold() for value in values if value)


def _is_entry_role(raw_role: str) -> bool:
    return any(marker in raw_role for marker in _ENTRY_ROLE_MARKERS)


def _is_post_lore_role(raw_role: str) -> bool:
    return any(marker in raw_role for marker in _POST_LORE_ROLE_MARKERS)


def _is_current_field_from_historical_section(raw_role: str) -> bool:
    if "lore history" not in raw_role and "history" not in raw_role:
        return False
    if _is_entry_role(raw_role):
        return False
    if "quest" in raw_role or "storyline" in raw_role:
        return False
    return True


def _is_excluded_role(raw_role: str) -> bool:
    return any(marker in raw_role for marker in _EXCLUDED_ROLE_MARKERS)


def _is_excluded_noncanon(raw_role: str, snippet: str, categories: list[str]) -> bool:
    if _is_excluded_role(raw_role):
        return True
    lowered = f"{raw_role} {snippet}".casefold()
    if "non-canon" in lowered or "non canon" in lowered or "removed from world of warcraft" in lowered:
        return True
    signal = strict_generation_category_signal(categories)
    return signal.disposition == "strong_drop"


def strict_generation_category_signal(categories: list[str]) -> CategorySignal:
    """Category gate for generated content sources.

    Mixed pages are common on Warcraft Wiki. A page with valid current-retail structural categories
    plus an RPG or speculation category should stay eligible for temporal classification; only
    direct non-canon/removed category evidence remains a hard exclusion. RPG/speculation-only pages
    are deferred with ``soft_drop`` so downstream selection can avoid them unless stronger evidence
    exists elsewhere.
    """
    category_values = [str(category).replace("_", " ").strip() for category in categories if str(category).strip()]
    direct = " ".join(value.casefold() for value in category_values)
    base = classify_page_categories(category_values)
    mixed_valid = _has_mixed_valid_category(category_values)
    if any(token in direct for token in _DIRECT_NONCANON_TOKENS):
        return CategorySignal(
            bucket="noise",
            disposition="strong_drop",
            matched_tokens=tuple(token for token in _DIRECT_NONCANON_TOKENS if token in direct),
            reasons=("strict_generation_category_exclusion",),
        )
    if base.disposition in {"strong_drop", "soft_drop"} and mixed_valid:
        return CategorySignal(
            bucket="concept",
            disposition="review",
            matched_tokens=tuple(token for token in _MIXED_VALID_CATEGORY_TOKENS if token in direct),
            reasons=("mixed_valid_generation_category",),
        )
    has_valid_signal = base.disposition in {"strong_include", "review"} and (
        base.bucket != "noise" or mixed_valid
    )
    if any(token in direct for token in _DIRECT_EXCLUSION_TOKENS) and not has_valid_signal:
        return CategorySignal(
            bucket="noise",
            disposition="strong_drop",
            matched_tokens=tuple(token for token in _DIRECT_EXCLUSION_TOKENS if token in direct),
            reasons=("strict_generation_category_exclusion",),
        )
    if any(token in direct for token in _DEFER_CATEGORY_TOKENS) and not has_valid_signal:
        return CategorySignal(
            bucket="noise",
            disposition="soft_drop",
            matched_tokens=tuple(token for token in _DEFER_CATEGORY_TOKENS if token in direct),
            reasons=("strict_generation_category_defer",),
        )
    return base


def _has_mixed_valid_category(categories: list[str]) -> bool:
    direct = " ".join(category.casefold() for category in categories)
    return any(token in direct for token in _MIXED_VALID_CATEGORY_TOKENS)


def _dominant_scope(scopes: list[str]) -> str:
    if not scopes:
        return ""
    priority = [
        EXCLUDED_NONCANON,
        POST_ACTIVE_LORE,
        ACTIVE_STORYLINE_OUTCOME,
        ACTIVE_STORYLINE,
        AMBIGUOUS_TEMPORAL,
        ENTRY_STATE,
        PRE_ENTRY_HISTORY,
    ]
    for scope in priority:
        if scope in scopes:
            return scope
    return scopes[0]


def _truncate(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."
