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
import re
from dataclasses import dataclass, field, replace
from typing import Any, cast

from pipeline.ai.config import load_ai_settings
from pipeline.common.draft_vocab import expansion_release_order
from pipeline.common.wiki_category_registry import CategorySignal, classify_page_categories
from pipeline.generate.draft.claims import (
    CLAIM_ELIGIBLE_FIELDS,
    extract_canonical_claim_decision_rows,
)
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

SAFE_BACKGROUND = "safe_background"
SAFE_ENTRY_CONTEXT = "safe_entry_context"
SAFE_SETUP_HOOK = "safe_setup_hook"
ENCOUNTER_SETUP = "encounter_setup"
ACTIVE_MECHANICS_STATE = "active_mechanics_state"
ACTIVE_OUTCOME = "active_outcome"
POST_ACTIVE_REFERENCE = "post_active_reference"
UNSAFE_COMPLETION_DETAIL = "unsafe_completion_detail"
UNKNOWN_SPOILER_SAFETY = "unknown_spoiler_safety"

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
_SPOILER_SAFETY_VALUES = (
    SAFE_BACKGROUND,
    SAFE_ENTRY_CONTEXT,
    SAFE_SETUP_HOOK,
    ENCOUNTER_SETUP,
    ACTIVE_MECHANICS_STATE,
    ACTIVE_OUTCOME,
    POST_ACTIVE_REFERENCE,
    UNSAFE_COMPLETION_DETAIL,
    UNKNOWN_SPOILER_SAFETY,
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
# Contract fields that mark a currently-active, contested locus (not merely a current entity).
# Used to detect when an entry-state ``event`` claim is actually the resolution of an active
# storyline. Deliberately excludes ``current_locations``/``current_factions``: a held location
# (e.g. reclaimed Hearthglen) is current but not contested, and must stay history-eligible.
_ACTIVE_CONFLICT_CONTRACT_FIELDS = (
    "active_conflicts",
    "active_storylines",
    "active_encounters",
    "current_threats",
)
# Contract fields whose entity linkage exempts a later-expansion seed/lore paragraph from the
# recency floor (Slice 3): the contested/active loci plus the contract's current locations and
# objectives. Deliberately excludes the pure identity fields (current_factions/inhabitants/
# controller) — merely NAMING a currently-present entity is identity context, not evidence that a
# later-expansion event is part of the current entry state (same reasoning as the adjudication
# rubric's non-independent-match caution).
_SEED_RECENCY_LINKAGE_CONTRACT_FIELDS = (
    *_ACTIVE_CONFLICT_CONTRACT_FIELDS,
    "current_locations",
    "current_objectives",
)
# Seed/lore narrative fields covered by the seed recency floor (Slice 3): the subject's own page
# narrative (history/currently/at-a-glance) plus the auxiliary lore-page pools. Roster/quest anchor
# fields (boss_pool, questline_pool) and the bulk entity pools stay out — they are current-content
# anchors or are handled by their own guards (character_pool has the stricter
# ``_character_profile_recency_override``, which has no contract-linkage escape hatch).
_SEED_NARRATIVE_FIELD_NAMES = frozenset(
    {
        "history_digest",
        "currently_input",
        "at_a_glance_input",
        "instance_lore_pool",
        "parent_lore_pool",
        "related_lore_pool",
    }
)
# Whole-phrase prose matching for contract linkage: casefolded, punctuation collapsed to spaces
# (apostrophes kept — wiki proper nouns like "Gahrron's" carry them).
_PROSE_MATCH_STRIP_RE = re.compile(r"[^0-9a-z']+")


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


@dataclass(frozen=True)
class ClaimTemporalClassification:
    temporal_scope: str
    history_eligibility: str
    spoiler_safety: str
    confidence: float
    rationale: str
    history_rationale: str = ""
    event_label: str = ""
    fallback_mode: str = "deterministic"
    structural_hints: list[str] = field(default_factory=list)


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
    # Expansion whose content defines the CURRENT playable version of this subject, as a soft,
    # relative recency anchor for temporal classification: {"label": str, "rank": int} or None.
    active_expansion: dict[str, Any] | None = None
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
            "active_expansion": self.active_expansion,
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
    return_claim_decisions: bool = False,
    return_claim_temporal_decisions: bool = False,
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

    # Cost scoping: only spend canonical LLM adjudication on fields whose claim views are rendered
    # (CLAIM_ELIGIBLE_FIELDS). Bulk descriptive pools (faction_pool, location_pool, quest_lore) keep
    # their deterministic classification and route at paragraph level — this is the dominant cost
    # lever (see memory: claim-extraction-live-cost-explosion).
    llm_candidates = [
        record
        for record in canonical_records
        if record.classification is not None
        and _needs_canonical_llm_adjudication(record.classification, record)
        and _record_in_claim_eligible_field(record)
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

    # Recency floors, after the LLM pass so they correct both deterministic and adjudicated
    # classifications. Fix 1: still-living characters' later-expansion profile lines that only
    # survived as entry_state via "current roster presence" (the Lilian Voss leak). Slice 3: the
    # seed/lore sibling — later-expansion seed narrative with no entry-state contract linkage
    # (the Fourth-War leak into WPL's currently/history). The stricter character guard wins when
    # both could apply.
    for record in canonical_records:
        guard = _character_profile_recency_override(record)
        if guard is None:
            guard = _seed_narrative_recency_override(record)
        if guard is not None:
            record.classification = _with_canonical_history_defaults(
                guard,
                appearances=record.appearances,
            )

    decisions: list[dict[str, Any]] = []
    canonical_decisions: list[dict[str, Any]] = []
    claim_decisions: list[dict[str, Any]] = []
    claim_temporal_decisions: list[dict[str, Any]] = []
    if return_claim_decisions or return_claim_temporal_decisions:
        claim_decisions = extract_canonical_claim_decision_rows(canonical_records, run_id=run_id)
    if return_claim_temporal_decisions:
        claim_temporal_decisions = classify_claims_temporal(
            claim_decisions,
            canonical_records,
            run_id=run_id,
        )
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
    if return_claim_decisions:
        outputs.append(claim_decisions)
    if return_claim_temporal_decisions:
        outputs.append(claim_temporal_decisions)
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


# --- Expansion recency (soft, relative temporal signal) ------------------------------------------
# Expansion chronology is a deliberately-permitted SOFT prior (the "no expansion chronology" rule was
# relaxed). A paragraph from a later expansion-edit section than the subject's active-content
# expansion leans post_active; earlier/same leans pre_entry/entry. Ranks come from the ordered
# release list in the shared draft vocab; the LLM rubric still governs and can override.
_CURRENT_ANCHOR_FIELDS = frozenset(
    {"at_a_glance_input", "currently_input", "boss_pool", "geography_input"}
)


def _expansion_rank_for_role(role: str) -> int | None:
    """Rank of the expansion whose shorthand appears in a section-role string, or None."""
    role_lower = str(role).lower()
    for index, token in enumerate(expansion_release_order()):
        if token and token in role_lower:
            return index
    return None


def _paragraph_expansion_rank(record: CanonicalEvidenceRecord) -> int | None:
    """Latest expansion rank among a paragraph's section-role appearances, or None if untagged."""
    ranks: list[int] = []
    for appearance in record.appearances:
        for key in ("raw_section_role", "section_role"):
            rank = _expansion_rank_for_role(str(appearance.get(key, "")))
            if rank is not None:
                ranks.append(rank)
    return max(ranks) if ranks else None


def _active_expansion_rank(boundary: dict[str, Any]) -> int | None:
    contract = boundary.get("entry_state_contract")
    if not isinstance(contract, dict):
        return None
    active = contract.get("active_expansion")
    if not isinstance(active, dict):
        return None
    rank = active.get("rank")
    return rank if isinstance(rank, int) else None


def _expansion_recency(paragraph_rank: int | None, active_rank: int | None) -> str:
    if paragraph_rank is None or active_rank is None:
        return "unknown"
    if paragraph_rank > active_rank:
        return "later"
    if paragraph_rank < active_rank:
        return "earlier"
    return "same"


def _record_appears_in_character_pool(record: CanonicalEvidenceRecord) -> bool:
    return any(
        str(appearance.get("field_name", "")).strip() == "character_pool"
        for appearance in record.appearances
    )


def _character_profile_recency_override(
    record: CanonicalEvidenceRecord,
) -> TemporalClassification | None:
    """Guard: a character-profile paragraph from an expansion strictly LATER than the subject's
    active-content expansion cannot be entry_state/pre_entry_history for THIS instance.

    Floors such a paragraph to post_active_lore, overriding the "current roster presence" pull that
    otherwise leaks a still-living character's whole modern biography into an instance card (the
    Lilian Voss leak). Roster presence is a *legitimate* current-state match — that is why it cannot
    be filtered as a non-independent one — but a biography paragraph describing a later-expansion
    event still post-dates the current playable content no matter who it is about. Deliberately
    narrow: gated on character_pool + strictly-'later' recency, so the instance's own active-expansion
    section (recency 'same') is untouched and this does not reinstate a blanket expansion-era rule —
    expansion chronology stays a soft signal elsewhere (memory: expansion-chronology-now-soft-signal).
    """
    classification = record.classification
    if classification is None:
        return None
    if classification.scope not in {ENTRY_STATE, PRE_ENTRY_HISTORY}:
        return None
    if not _record_appears_in_character_pool(record):
        return None
    recency = _expansion_recency(
        _paragraph_expansion_rank(record), _active_expansion_rank(record.boundary)
    )
    if recency != "later":
        return None
    boundary_id = str(record.boundary.get("boundary_id", "")).strip()
    return TemporalClassification(
        POST_ACTIVE_LORE,
        max(classification.confidence, 0.6),
        "character_profile_later_expansion_non_independent_roster_presence",
        boundary_id,
        "character_profile_recency_guard",
        event_label=classification.event_label,
    )


def _record_appears_in_seed_narrative_field(record: CanonicalEvidenceRecord) -> bool:
    return any(
        str(appearance.get("field_name", "")).strip() in _SEED_NARRATIVE_FIELD_NAMES
        for appearance in record.appearances
    )


def _normalized_prose_match_text(value: object) -> str:
    """Casefolded text with punctuation collapsed to single spaces, for whole-phrase matching."""
    text = str(value or "").replace("_", " ").casefold()
    return " ".join(_PROSE_MATCH_STRIP_RE.sub(" ", text).split())


def _phrase_in_prose(term: str, prose: str) -> bool:
    return bool(term) and f" {term} " in f" {prose} "


def _paragraph_matches_entry_state_contract(record: CanonicalEvidenceRecord) -> bool:
    """True when the paragraph's entities link it to the contract's active conflicts,
    current locations, or objectives.

    ``_claim_matches_active_conflict_contract``-style matching lifted to paragraph level: exact
    normalized contract entry labels/IDs against the paragraph's appearance metadata
    (faction/location/character names and ids) plus whole-phrase presence in the paragraph text.
    Deliberately NOT ``_canonical_contract_relation`` — its source_id match would link every seed
    paragraph trivially (contract anchors come from the seed page itself). The subject's own
    zone/instance name never counts: every seed paragraph names its subject.
    """
    contract = record.boundary.get("entry_state_contract")
    if not isinstance(contract, dict):
        return False
    subject_terms = _subject_name_terms(record)
    contract_terms: set[str] = set()
    for contract_field in _SEED_RECENCY_LINKAGE_CONTRACT_FIELDS:
        values = contract.get(contract_field)
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            _add_normalized_contract_term(contract_terms, entry.get("label"))
            for id_key in _CONTRACT_ID_KEYS:
                _add_normalized_contract_term(contract_terms, entry.get(id_key))
    contract_terms -= subject_terms
    if not contract_terms:
        return False
    candidate_terms: set[str] = set()
    for ref in record.refs:
        labels, identifiers = _contract_candidate_terms(ref["row"], ref["item"])
        candidate_terms |= labels | identifiers
    candidate_terms -= subject_terms
    if candidate_terms & contract_terms:
        return True
    prose = _normalized_prose_match_text(record.snippet)
    return any(
        _phrase_in_prose(_normalized_prose_match_text(term), prose) for term in contract_terms
    )


def _seed_narrative_recency_override(
    record: CanonicalEvidenceRecord,
) -> TemporalClassification | None:
    """Guard (Slice 3): a seed/lore narrative paragraph from an expansion strictly LATER than the
    subject's active-content expansion, with no entity linkage to the entry-state contract, cannot
    stand as entry_state or history_setup_bridge.

    Deterministic floor under boundary authority: a confident LLM boundary verdict remains
    authoritative in general, but a later-expansion seed paragraph must show contract linkage to
    claim it describes the current playable state (the Fourth-War "War Frontiers" paragraph that
    framed WPL's ``currently`` and final history section). Contract linkage is the escape hatch
    that keeps expansion chronology a soft signal (memory: expansion-chronology-now-soft-signal) —
    a later-expansion paragraph about the zone's own active conflict survives. Floors to
    post_active_lore; ``_with_canonical_history_defaults`` then derives
    history_excluded_post_active for history appearances, and the canonical decisions sidecar
    records the floor (distinct reason; the structural hint keeps the overridden verdict).
    """
    classification = record.classification
    if classification is None:
        return None
    if (
        classification.scope != ENTRY_STATE
        and classification.history_eligibility != HISTORY_SETUP_BRIDGE
    ):
        return None
    if not _record_appears_in_seed_narrative_field(record):
        return None
    recency = _expansion_recency(
        _paragraph_expansion_rank(record), _active_expansion_rank(record.boundary)
    )
    if recency != "later":
        return None
    if _paragraph_matches_entry_state_contract(record):
        return None
    boundary_id = str(record.boundary.get("boundary_id", "")).strip()
    return TemporalClassification(
        POST_ACTIVE_LORE,
        max(classification.confidence, 0.6),
        "seed_later_expansion_no_contract_linkage",
        boundary_id,
        "seed_narrative_recency_guard:floored_"
        f"{classification.fallback_mode}_{classification.scope}",
        event_label=classification.event_label,
        history_eligibility="",
    )


def _current_anchor_snippets(rows: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    snippets: list[str] = []
    for row in rows:
        if str(row.get("field_name", "")).strip() not in _CURRENT_ANCHOR_FIELDS:
            continue
        for item in row.get("evidence_items", []) or []:
            text = str(item.get("snippet") or item.get("text") or "").strip()
            if text:
                snippets.append(text[:400])
                if len(snippets) >= limit:
                    return snippets
    return snippets


def _derive_active_expansion(rows: list[dict[str, Any]], *, name: str) -> dict[str, Any] | None:
    """One-shot LLM extraction of the subject's active-content expansion.

    Reads the current-anchor evidence (at-a-glance / current dungeon description / roster) and asks
    which expansion introduced or last redesigned the CURRENT playable version. Returns
    {"label", "rank"} or None (LLM unavailable, no anchors, or 'unknown' — the recency prior then
    simply is not applied).
    """
    if _llm_temporal_adjudication_disabled():
        return None
    snippets = _current_anchor_snippets(rows)
    if not snippets:
        return None
    tokens = list(expansion_release_order())
    try:
        result = llm_json_with_retry(
            required_keys=("expansion",),
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["expansion"],
                "properties": {"expansion": {"type": "string", "enum": [*tokens, "unknown"]}},
            },
            system_prompt=(
                "You identify which World of Warcraft expansion introduced or last redesigned the "
                "CURRENT playable version of a zone or instance, from its current description. "
                "Return exactly one token from the allowed list, or 'unknown' if the current "
                "content's expansion is not stated. Judge the CURRENT version, not older lore."
            ),
            user_prompt=(
                f"Subject: {name}\nAllowed expansion tokens (release order): {tokens}\n\n"
                "Current-state evidence:\n" + "\n---\n".join(snippets)
            ),
            response_schema_name="wiki_first_active_expansion",
            substep="wiki_first_active_expansion",
            max_attempts=2,
        )
    except Exception:  # pragma: no cover - provider failures leave the prior unapplied
        return None
    label = str(result.get("expansion", "")).strip().lower()
    rank = _expansion_rank_for_role(label)
    if rank is None:
        return None
    return {"label": label, "rank": rank}


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


def _record_in_claim_eligible_field(record: CanonicalEvidenceRecord) -> bool:
    """True if the record appears in a field whose claim views are rendered (see CLAIM_ELIGIBLE_FIELDS).

    Bulk descriptive pools (faction_pool, location_pool, quest_lore) route at paragraph level, so
    spending an LLM call to disambiguate their ``ambiguous_temporal`` paragraphs is wasted — they
    stay ambiguous (deterministically filtered) like any other paragraph-level evidence. This keeps
    canonical adjudication scoped to the same small set as claim extraction.
    """
    field_names = {str(ref.get("field_name", "")).strip() for ref in record.refs}
    return bool(field_names & CLAIM_ELIGIBLE_FIELDS)


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


def classify_claims_temporal(
    claim_decisions: list[dict[str, Any]],
    canonical_records: list[CanonicalEvidenceRecord],
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    """Classify extracted source claims relative to the entry-state boundary.

    This produces an internal sidecar only. Existing routed paragraph evidence remains untouched
    until claim-level routing lands in a later slice.
    """
    record_by_id = {record.canonical_evidence_id: record for record in canonical_records}
    entries: list[dict[str, Any]] = []
    for decision in claim_decisions:
        canonical_id = str(decision.get("canonical_evidence_id", "")).strip()
        record = record_by_id.get(canonical_id)
        if record is None:
            continue
        claims = decision.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            classification = _classify_claim_temporal_deterministic(
                claim=claim,
                claim_decision=decision,
                record=record,
            )
            entries.append(
                {
                    "decision": decision,
                    "record": record,
                    "claim": claim,
                    "classification": classification,
                }
            )

    # Cost scoping: only spend LLM claim-temporal adjudication on fields whose claim views are
    # rendered. Bulk-pool claims that want LLM keep their deterministic classification instead.
    llm_entries = [
        entry
        for entry in entries
        if entry["classification"].fallback_mode == "needs_llm"
        and _record_in_claim_eligible_field(entry["record"])
    ]
    if llm_entries and not _llm_temporal_adjudication_disabled():
        overrides = adjudicate_claim_temporal_classifications_llm(llm_entries)
        for entry in entries:
            override = overrides.get(str(entry["claim"].get("claim_id", "")).strip())
            if override is not None:
                entry["classification"] = override

    entries_by_canonical: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        canonical_id = str(entry["decision"].get("canonical_evidence_id", "")).strip()
        entries_by_canonical.setdefault(canonical_id, []).append(entry)

    # A setup-bridge paragraph that states the zone's current condition can also carry the
    # resolution of an active storyline (e.g. "war still raged in Andorhal ... the Forsaken gained
    # control"). The per-claim deterministic pass inherits the paragraph's entry-state label onto
    # every claim, so those outcome claims would leak into history/current prose. Re-label them.
    _propagate_active_storyline_outcomes(entries_by_canonical)

    rows: list[dict[str, Any]] = []
    for decision in claim_decisions:
        canonical_id = str(decision.get("canonical_evidence_id", "")).strip()
        record = record_by_id.get(canonical_id)
        if record is None:
            continue
        claim_entries = entries_by_canonical.get(canonical_id, [])
        claim_rows = []
        for entry in claim_entries:
            row = _claim_temporal_decision_row(entry["claim"], entry["classification"])
            # Disagreement telemetry: a claim whose final scope diverges from its canonical
            # paragraph verdict is recorded, so a deterministic pass silently reverting the
            # paragraph-level LLM judgment is visible in the decisions sidecar (drives audits).
            paragraph = record.classification
            if paragraph is not None and row["temporal_scope"] != paragraph.scope:
                row["paragraph_scope_divergence"] = {
                    "paragraph_scope": paragraph.scope,
                    "paragraph_fallback_mode": paragraph.fallback_mode,
                    "paragraph_confidence": paragraph.confidence,
                    "claim_fallback_mode": row["fallback_mode"],
                }
            claim_rows.append(row)
        rows.append(
            {
                "canonical_evidence_id": canonical_id,
                "subject_id": str(decision.get("subject_id", record.subject_id)),
                "subject_type": str(decision.get("subject_type", record.subject_type)),
                "run_id": run_id or str(decision.get("run_id", "unknown")) or "unknown",
                "source_id": str(decision.get("source_id", record.source_id)),
                "source_title": str(decision.get("source_title", record.source_title)),
                "source_excerpt": str(decision.get("source_excerpt", record.snippet)),
                "appearance_count": decision.get("appearance_count", len(record.appearances)),
                "appearances": decision.get("appearances", record.appearances),
                "extraction_mode": str(decision.get("extraction_mode", "")),
                "claim_count": len(claim_rows),
                "paragraph_aggregate": _paragraph_aggregate_from_claims(
                    claim_rows,
                    fallback_classification=record.classification,
                ),
                "claims": claim_rows,
            }
        )
    return rows


def _classify_claim_temporal_deterministic(
    *,
    claim: dict[str, Any],
    claim_decision: dict[str, Any],
    record: CanonicalEvidenceRecord,
) -> ClaimTemporalClassification:
    paragraph = record.classification
    boundary_id = str(record.boundary.get("boundary_id", "")).strip()
    claim_type = str(claim.get("claim_type", "")).strip()
    appearances = claim_decision.get("appearances")
    if not isinstance(appearances, list):
        appearances = record.appearances
    field_names = {
        str(appearance.get("field_name", "")).strip()
        for appearance in appearances
        if isinstance(appearance, dict)
    }
    structural_hints = _claim_structural_hints(
        claim=claim,
        record=record,
        appearances=appearances,
    )

    if paragraph is not None:
        if paragraph.scope == EXCLUDED_NONCANON:
            return ClaimTemporalClassification(
                EXCLUDED_NONCANON,
                HISTORY_EXCLUDED_POST_ACTIVE,
                UNKNOWN_SPOILER_SAFETY,
                0.94,
                "claim inherits non-canon/source exclusion from canonical paragraph",
                "excluded source evidence is never history-eligible",
                paragraph.event_label,
                "deterministic",
                structural_hints,
            )
        if paragraph.scope == POST_ACTIVE_LORE:
            return ClaimTemporalClassification(
                POST_ACTIVE_LORE,
                HISTORY_EXCLUDED_POST_ACTIVE,
                POST_ACTIVE_REFERENCE,
                0.9,
                "claim inherits later/off-screen lore label from canonical paragraph",
                "post-active references are excluded from entry-history prose",
                paragraph.event_label,
                "deterministic",
                structural_hints,
            )
        if paragraph.scope == PRE_ENTRY_HISTORY:
            return ClaimTemporalClassification(
                PRE_ENTRY_HISTORY,
                HISTORY_BACKGROUND,
                SAFE_BACKGROUND,
                0.86,
                "claim inherits pre-entry history label from canonical paragraph",
                "pre-entry background is history-eligible",
                paragraph.event_label,
                "deterministic",
                structural_hints,
            )
        if paragraph.scope == ACTIVE_STORYLINE_OUTCOME and _claim_needs_mixed_llm(
            claim_decision=claim_decision,
            record=record,
        ):
            return ClaimTemporalClassification(
                AMBIGUOUS_TEMPORAL,
                HISTORY_EXCLUDED_OUTCOME,
                UNKNOWN_SPOILER_SAFETY,
                0.44,
                "claim in mixed/outcome paragraph requires claim-level boundary classification",
                "mixed paragraph claims are not history-eligible until classified",
                paragraph.event_label,
                "needs_llm",
                structural_hints + ["mixed_outcome_paragraph"],
            )
        if paragraph.scope == ACTIVE_STORYLINE_OUTCOME:
            return ClaimTemporalClassification(
                ACTIVE_STORYLINE_OUTCOME,
                HISTORY_EXCLUDED_OUTCOME,
                ACTIVE_OUTCOME,
                0.9,
                "claim inherits active storyline outcome label from canonical paragraph",
                "active outcomes are excluded from pre-entry history",
                paragraph.event_label,
                "deterministic",
                structural_hints,
            )
        if paragraph.scope == ENTRY_STATE:
            safety = _entry_state_claim_spoiler_safety(claim_type, field_names)
            history_eligibility = paragraph.history_eligibility or HISTORY_NOT_APPLICABLE
            if history_eligibility not in _HISTORY_ELIGIBILITY_VALUES:
                history_eligibility = HISTORY_NOT_APPLICABLE
            return ClaimTemporalClassification(
                ENTRY_STATE,
                history_eligibility,
                safety,
                0.82,
                "claim inherits entry-state label from canonical paragraph",
                paragraph.history_reason or "entry-state claim history eligibility inherited",
                paragraph.event_label,
                "deterministic",
                structural_hints,
            )
        if paragraph.scope == ACTIVE_STORYLINE:
            return ClaimTemporalClassification(
                ACTIVE_STORYLINE,
                HISTORY_NOT_APPLICABLE,
                SAFE_SETUP_HOOK,
                0.78,
                "claim inherits active storyline setup label from canonical paragraph",
                "active storyline setup is not background history",
                paragraph.event_label,
                "deterministic",
                structural_hints,
            )

    if claim_type == "encounter_state" or "boss_pool" in field_names:
        return ClaimTemporalClassification(
            ENTRY_STATE,
            HISTORY_NOT_APPLICABLE,
            ACTIVE_MECHANICS_STATE,
            0.72,
            "encounter/roster claim is current instance evidence",
            "encounter mechanics are not background history",
            "",
            "deterministic",
            structural_hints + ["encounter_or_boss_pool"],
        )

    relation = _claim_contract_relation(claim, record.boundary)
    if relation.get("matched"):
        return ClaimTemporalClassification(
            ENTRY_STATE,
            HISTORY_SETUP_BRIDGE if _canonical_has_field(record, "history_digest") else HISTORY_NOT_APPLICABLE,
            SAFE_ENTRY_CONTEXT,
            0.68,
            "claim matches entry-state contract terms",
            "contract-matched setup can bridge into current context",
            "",
            "deterministic",
            structural_hints + ["claim_contract_match"],
        )

    return ClaimTemporalClassification(
        AMBIGUOUS_TEMPORAL,
        HISTORY_EXCLUDED_POST_ACTIVE,
        UNKNOWN_SPOILER_SAFETY,
        0.42,
        "claim requires boundary-relative temporal classification",
        "ambiguous claim is excluded until classified",
        "",
        "needs_llm",
        structural_hints + [f"boundary_id:{boundary_id}" if boundary_id else "no_boundary_id"],
    )


def adjudicate_claim_temporal_classifications_llm(
    entries: list[dict[str, Any]],
) -> dict[str, ClaimTemporalClassification]:
    overrides: dict[str, ClaimTemporalClassification] = {}
    for group in _claim_temporal_llm_groups(entries):
        result: dict[str, Any]
        try:
            result = llm_json_with_retry(
                required_keys=("classifications",),
                response_json_schema=_claim_temporal_schema(),
                system_prompt=_claim_temporal_system_prompt(),
                user_prompt=_claim_temporal_prompt(group),
                response_schema_name="wiki_first_claim_temporal_classification",
                substep="wiki_first_claim_temporal_classification",
                max_attempts=2,
            )
        except Exception as exc:  # pragma: no cover - provider failures keep fallback labels
            for entry in group:
                prior = entry["classification"]
                claim_id = str(entry["claim"].get("claim_id", "")).strip()
                if claim_id:
                    overrides[claim_id] = ClaimTemporalClassification(
                        prior.temporal_scope,
                        prior.history_eligibility,
                        prior.spoiler_safety,
                        prior.confidence,
                        f"{prior.rationale}; llm_claim_temporal_failed={exc.__class__.__name__}",
                        prior.history_rationale,
                        prior.event_label,
                        "llm_failed",
                        prior.structural_hints,
                    )
            continue
        rows = result.get("classifications")
        if not isinstance(rows, list):
            continue
        entry_by_claim_id = {
            str(entry["claim"].get("claim_id", "")).strip(): entry for entry in group
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            claim_id = str(row.get("claim_id", "")).strip()
            matched_entry = entry_by_claim_id.get(claim_id)
            if matched_entry is None:
                continue
            scope = str(row.get("temporal_scope", "")).strip()
            history_eligibility = str(row.get("history_eligibility", "")).strip()
            spoiler_safety = str(row.get("spoiler_safety", "")).strip()
            if scope not in TEMPORAL_SCOPES:
                continue
            if history_eligibility not in _HISTORY_ELIGIBILITY_VALUES:
                history_eligibility = HISTORY_NOT_APPLICABLE
            history_eligibility, history_reason = _sanitize_history_eligibility(
                "history_digest"
                if _canonical_has_field(matched_entry["record"], "history_digest")
                else "",
                scope,
                history_eligibility,
                str(row.get("history_rationale", "")).strip(),
            )
            if spoiler_safety not in _SPOILER_SAFETY_VALUES:
                spoiler_safety = _default_spoiler_safety(scope)
            confidence_value = row.get("confidence", 0.7)
            confidence = float(confidence_value) if isinstance(confidence_value, (int, float)) else 0.7
            overrides[claim_id] = ClaimTemporalClassification(
                scope,
                history_eligibility,
                _sanitize_spoiler_safety(scope, spoiler_safety),
                max(0.0, min(1.0, confidence)),
                str(row.get("rationale", "")).strip() or "llm claim temporal classification",
                history_reason,
                str(row.get("event_label", "")).strip(),
                "llm_claim_boundary",
                matched_entry["classification"].structural_hints,
            )
    return overrides


def _claim_temporal_decision_row(
    claim: dict[str, Any],
    classification: ClaimTemporalClassification,
) -> dict[str, Any]:
    return {
        "claim_id": str(claim.get("claim_id", "")).strip(),
        "canonical_evidence_id": str(claim.get("canonical_evidence_id", "")).strip(),
        "claim_text": str(claim.get("claim_text", "")).strip(),
        "claim_type": str(claim.get("claim_type", "")).strip(),
        "source_sentence_indexes": claim.get("source_sentence_indexes", []),
        "source_char_spans": claim.get("source_char_spans", []),
        "source_excerpt": str(claim.get("source_excerpt", "")).strip(),
        "entities": claim.get("entities", []),
        "temporal_scope": classification.temporal_scope,
        "history_eligibility": classification.history_eligibility,
        "spoiler_safety": classification.spoiler_safety,
        "confidence": classification.confidence,
        "rationale": classification.rationale,
        "history_rationale": classification.history_rationale,
        "event_label": classification.event_label,
        "fallback_mode": classification.fallback_mode,
        "structural_hints": classification.structural_hints,
    }


def _paragraph_aggregate_from_claims(
    claim_rows: list[dict[str, Any]],
    *,
    fallback_classification: TemporalClassification | None,
) -> dict[str, Any]:
    scopes = [str(row.get("temporal_scope", "")).strip() for row in claim_rows]
    spoiler_values = [str(row.get("spoiler_safety", "")).strip() for row in claim_rows]
    scope = _dominant_scope(scopes)
    if not scope and fallback_classification is not None:
        scope = fallback_classification.scope
    history_eligibility = _aggregate_history_eligibility(claim_rows, scope)
    return {
        "temporal_scope": scope,
        "history_eligibility": history_eligibility,
        "spoiler_safety": _aggregate_spoiler_safety(spoiler_values),
        "claim_count_by_scope": {
            value: scopes.count(value) for value in sorted(set(scopes)) if value
        },
        "claim_count": len(claim_rows),
        "compatibility_source": "claim_labels",
    }


def _claim_structural_hints(
    *,
    claim: dict[str, Any],
    record: CanonicalEvidenceRecord,
    appearances: list[Any],
) -> list[str]:
    hints: list[str] = []
    claim_type = str(claim.get("claim_type", "")).strip()
    if claim_type:
        hints.append(f"claim_type:{claim_type}")
    for appearance in appearances:
        if not isinstance(appearance, dict):
            continue
        field_name = str(appearance.get("field_name", "")).strip()
        if field_name:
            hints.append(f"field:{field_name}")
        source_kind = str(appearance.get("source_kind", "")).strip()
        if source_kind:
            hints.append(f"source_kind:{source_kind}")
        for role_key in ("raw_section_role", "section_role", "content_role", "auxiliary_role"):
            role = str(appearance.get(role_key, "")).strip()
            if role:
                hints.append(f"{role_key}:{role}")
        cluster_id = str(appearance.get("cluster_id", "")).strip()
        if cluster_id:
            hints.append("quest_cluster_linked")
        quest_node_id = str(appearance.get("quest_node_id", "")).strip()
        if quest_node_id:
            hints.append("quest_node_linked")
        if field_name == "boss_pool":
            hints.append("boss_pool")
    paragraph = record.classification
    if paragraph is not None:
        hints.append(f"paragraph_scope:{paragraph.scope}")
        if paragraph.history_eligibility:
            hints.append(f"paragraph_history:{paragraph.history_eligibility}")
        if paragraph.structural_hint:
            hints.append(f"paragraph_structural_hint:{paragraph.structural_hint}")
        if paragraph.reason:
            hints.append(f"paragraph_reason:{paragraph.reason[:120]}")
    for structural in record.structural_classifications:
        if structural.structural_hint:
            hints.append(f"appearance_structural_hint:{structural.structural_hint}")
        if structural.reason:
            hints.append(f"appearance_reason:{structural.reason[:120]}")
    category_signal = strict_generation_category_signal(record.source_categories)
    hints.append(f"category_disposition:{category_signal.disposition}")
    if category_signal.bucket:
        hints.append(f"category_bucket:{category_signal.bucket}")
    for reason in category_signal.reasons:
        hints.append(f"category_reason:{reason}")
    relation = _claim_contract_relation(claim, record.boundary)
    if relation.get("matched"):
        hints.append("entry_contract_match")
        for field in relation.get("matched_fields", []):
            hints.append(f"entry_contract_field:{field}")
    return list(dict.fromkeys(hints))


def _claim_needs_mixed_llm(
    *,
    claim_decision: dict[str, Any],
    record: CanonicalEvidenceRecord,
) -> bool:
    claims = claim_decision.get("claims")
    if isinstance(claims, list) and len(claims) > 1:
        return True
    return False


def _entry_state_claim_spoiler_safety(claim_type: str, field_names: set[str]) -> str:
    if claim_type == "encounter_state" or "boss_pool" in field_names:
        return ACTIVE_MECHANICS_STATE
    if claim_type == "objective" or field_names.intersection(_ACTIVE_FIELD_NAMES):
        return SAFE_SETUP_HOOK
    return SAFE_ENTRY_CONTEXT


def _default_spoiler_safety(scope: str) -> str:
    if scope == PRE_ENTRY_HISTORY:
        return SAFE_BACKGROUND
    if scope == ENTRY_STATE:
        return SAFE_ENTRY_CONTEXT
    if scope == ACTIVE_STORYLINE:
        return SAFE_SETUP_HOOK
    if scope == ACTIVE_STORYLINE_OUTCOME:
        return ACTIVE_OUTCOME
    if scope == POST_ACTIVE_LORE:
        return POST_ACTIVE_REFERENCE
    return UNKNOWN_SPOILER_SAFETY


def _sanitize_spoiler_safety(scope: str, spoiler_safety: str) -> str:
    if scope == ACTIVE_STORYLINE_OUTCOME and spoiler_safety not in {
        ACTIVE_OUTCOME,
        UNSAFE_COMPLETION_DETAIL,
    }:
        return ACTIVE_OUTCOME
    if scope == POST_ACTIVE_LORE and spoiler_safety != POST_ACTIVE_REFERENCE:
        return POST_ACTIVE_REFERENCE
    if scope == EXCLUDED_NONCANON:
        return UNKNOWN_SPOILER_SAFETY
    return spoiler_safety


def _claim_contract_relation(claim: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any]:
    contract = boundary.get("entry_state_contract")
    if not isinstance(contract, dict):
        return {"matched": False, "matched_fields": [], "matched_labels": []}
    candidate_terms = _claim_candidate_terms(claim)
    matched_fields: set[str] = set()
    matched_labels: set[str] = set()
    for contract_field in _CONTRACT_MATCH_FIELDS:
        values = contract.get(contract_field)
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            terms = {
                _normalize_contract_term(entry.get("label")),
                *(
                    _normalize_contract_term(entry.get(id_key))
                    for id_key in _CONTRACT_ID_KEYS
                ),
            }
            terms.discard("")
            if candidate_terms.intersection(terms):
                matched_fields.add(contract_field)
                label = str(entry.get("label", "")).strip()
                if label:
                    matched_labels.add(label)
    return {
        "matched": bool(matched_fields),
        "matched_fields": sorted(matched_fields),
        "matched_labels": sorted(matched_labels),
    }


def _claim_candidate_terms(claim: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    _add_normalized_contract_term(terms, claim.get("claim_text"))
    entities = claim.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            _add_normalized_contract_term(terms, entity.get("entity_id"))
            _add_normalized_contract_term(terms, entity.get("name"))
    return terms


def _claim_entity_terms(claim: dict[str, Any]) -> set[str]:
    """Normalized entity id/name terms for a claim (entities only, never the prose text)."""
    terms: set[str] = set()
    entities = claim.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            _add_normalized_contract_term(terms, entity.get("entity_id"))
            _add_normalized_contract_term(terms, entity.get("name"))
    return terms


def _claim_sentence_indexes(claim: dict[str, Any]) -> set[int]:
    indexes: set[int] = set()
    raw = claim.get("source_sentence_indexes")
    if isinstance(raw, list):
        for value in raw:
            try:
                indexes.add(int(value))
            except (TypeError, ValueError):
                continue
    return indexes


def _claim_matches_active_conflict_contract(claim: dict[str, Any], boundary: dict[str, Any]) -> bool:
    """True when the claim's resolved entities match a contested/active contract locus.

    Matches exact normalized entity labels/IDs against the active-conflict contract fields only,
    never substring scans over prose.
    """
    contract = boundary.get("entry_state_contract")
    if not isinstance(contract, dict):
        return False
    entity_terms = _claim_entity_terms(claim)
    if not entity_terms:
        return False
    for contract_field in _ACTIVE_CONFLICT_CONTRACT_FIELDS:
        values = contract.get(contract_field)
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            terms = {_normalize_contract_term(entry.get("label"))}
            for id_key in _CONTRACT_ID_KEYS:
                terms.add(_normalize_contract_term(entry.get(id_key)))
            terms.discard("")
            if entity_terms & terms:
                return True
    return False


def _active_storyline_outcome_classification(
    previous: ClaimTemporalClassification,
) -> ClaimTemporalClassification:
    return ClaimTemporalClassification(
        ACTIVE_STORYLINE_OUTCOME,
        HISTORY_EXCLUDED_OUTCOME,
        ACTIVE_OUTCOME,
        0.8,
        "event claim resolves an active storyline/conflict the page presents as current",
        "active storyline outcomes are excluded from entry-state history and current prose",
        previous.event_label,
        "deterministic",
        list(previous.structural_hints) + ["active_storyline_outcome_resolved"],
    )


# Minimum paragraph-verdict confidence for the LLM boundary pass to be treated as authoritative
# over deterministic claim-level heuristics. LLM boundary verdicts carry 0.84 when decisive and
# <= 0.5 when the model itself said "ambiguous" — only the decisive ones outrank heuristics.
_LLM_PARAGRAPH_VERDICT_MIN_CONFIDENCE = 0.7


def _paragraph_has_confident_llm_verdict(record: CanonicalEvidenceRecord) -> bool:
    """True when the page's LLM boundary pass confidently classified this whole paragraph.

    The canonical (paragraph-level) adjudicator sees the full paragraph in context, so its
    confident verdict is authoritative: deterministic claim passes may refine *within* it (e.g.
    excluding a resolving sentence flagged by a within-paragraph ``encounter_state`` sibling), but
    must never flip it on the strength of a broad *global* signal alone — an instance paragraph
    that merely NAMES a contested place while describing who now holds the site is standing setup,
    not a resolution of that conflict (the Scholomance/Gandling case). The reliable
    within-paragraph ``encounter_state`` sibling signal is unaffected and still anchors outcomes.
    """
    classification = record.classification
    if classification is None:
        return False
    return (
        classification.fallback_mode == "llm_boundary"
        and classification.confidence >= _LLM_PARAGRAPH_VERDICT_MIN_CONFIDENCE
    )


def _subject_name_terms(record: CanonicalEvidenceRecord) -> set[str]:
    """Normalized terms for the subject's own name.

    Excluded from the contested-locus set: the zone/instance's own name (e.g. "Western Plaguelands")
    is too broad to mark a specific contested place, and would otherwise drag safe sentences that
    merely mention the zone into the outcome bucket.
    """
    terms: set[str] = set()
    # Claims reference the subject by both its display name ("Western Plaguelands") and its id
    # ("zone-western-plaguelands"); exclude both forms.
    _add_normalized_contract_term(terms, record.subject_id)
    contract = record.boundary.get("entry_state_contract")
    if isinstance(contract, dict):
        _add_normalized_contract_term(terms, contract.get("name"))
    terms.discard("")
    return terms


# Claim types eligible to *anchor* an active-storyline outcome. A resolution can be extracted as a
# discrete happening (``event``, "the Forsaken gained control") or a resulting condition (``state``,
# "the Forsaken control Andorhal") — the extractor is nondeterministic between the two — so both
# anchor. ``encounter_state`` (the "still ongoing" marker) never anchors and is never re-labeled.
_OUTCOME_ANCHOR_CLAIM_TYPES = frozenset({"event", "state"})


def _propagate_active_storyline_outcomes(
    entries_by_canonical: dict[str, list[dict[str, Any]]],
) -> None:
    """Re-label entry-state claims that resolve an active storyline/conflict.

    A claim is an outcome *anchor* when it is an entry-state ``event``/``state`` claim whose entities
    either (a) overlap a sibling ``encounter_state`` claim in the same paragraph (a contested locus
    such as "war still raged in Andorhal"), or (b) match an active-conflict contract field. The
    outcome label then propagates to every claim sharing a source sentence with an anchor — a
    sentence that resolves a conflict carries the whole resolution, regardless of how each sub-claim
    was tagged ``event`` vs ``state``. The only claims spared are ``encounter_state`` ongoing markers
    (they live in a different, setup sentence), so safe setup and current-context claims survive —
    the safe-setup/exclude-outcome split from clarification Q2 of the temporal tracker.
    """
    for entries in entries_by_canonical.values():
        subject_terms: set[str] = set()
        for entry in entries:
            subject_terms |= _subject_name_terms(entry["record"])

        # Entities a sibling encounter_state claim marks as an active, unresolved conflict locus,
        # minus the subject's own name (too broad — it would over-match safe sentences).
        contested_terms: set[str] = set()
        for entry in entries:
            claim = entry["claim"]
            if str(claim.get("claim_type", "")).strip() == "encounter_state":
                contested_terms |= _claim_entity_terms(claim)
        contested_terms -= subject_terms

        anchor_sentences: set[int] = set()
        for entry in entries:
            if entry["classification"].temporal_scope != ENTRY_STATE:
                continue
            claim = entry["claim"]
            if str(claim.get("claim_type", "")).strip() not in _OUTCOME_ANCHOR_CLAIM_TYPES:
                continue
            # (a) A sibling encounter_state claim marks a still-active conflict locus in THIS
            # paragraph — a reliable within-paragraph resolution signal.
            resolves_local = bool(_claim_entity_terms(claim) & contested_terms)
            # (b) The claim's entities match a global active-conflict contract locus. This is a
            # broad heuristic: a paragraph the page's own LLM boundary pass confidently classified
            # — e.g. standing setup, "after failing at Andorhal, X fell back here and now holds
            # it" — merely NAMES the contested place; it does not resolve that conflict. Defer to
            # that considered paragraph verdict rather than let the global match override it.
            resolves_contract = _claim_matches_active_conflict_contract(
                claim, entry["record"].boundary
            )
            if resolves_contract and _paragraph_has_confident_llm_verdict(entry["record"]):
                resolves_contract = False
            if resolves_local or resolves_contract:
                anchor_sentences |= _claim_sentence_indexes(claim)
        if not anchor_sentences:
            continue

        for entry in entries:
            classification = entry["classification"]
            if classification.temporal_scope != ENTRY_STATE:
                continue
            claim = entry["claim"]
            # Keep the ongoing-state marker ("war still rages") safe; relabel every other claim that
            # shares the resolving sentence, regardless of its event/state tag.
            if str(claim.get("claim_type", "")).strip() == "encounter_state":
                continue
            if anchor_sentences & _claim_sentence_indexes(claim):
                entry["classification"] = _active_storyline_outcome_classification(classification)


def _aggregate_history_eligibility(claim_rows: list[dict[str, Any]], scope: str) -> str:
    values = [str(row.get("history_eligibility", "")).strip() for row in claim_rows]
    if HISTORY_EXCLUDED_OUTCOME in values or scope == ACTIVE_STORYLINE_OUTCOME:
        return HISTORY_EXCLUDED_OUTCOME
    if HISTORY_EXCLUDED_POST_ACTIVE in values or scope in {
        POST_ACTIVE_LORE,
        EXCLUDED_NONCANON,
        AMBIGUOUS_TEMPORAL,
    }:
        return HISTORY_EXCLUDED_POST_ACTIVE
    if HISTORY_SETUP_BRIDGE in values:
        return HISTORY_SETUP_BRIDGE
    if HISTORY_BACKGROUND in values:
        return HISTORY_BACKGROUND
    return HISTORY_NOT_APPLICABLE


def _aggregate_spoiler_safety(values: list[str]) -> str:
    priority = (
        UNSAFE_COMPLETION_DETAIL,
        ACTIVE_OUTCOME,
        POST_ACTIVE_REFERENCE,
        UNKNOWN_SPOILER_SAFETY,
        ACTIVE_MECHANICS_STATE,
        ENCOUNTER_SETUP,
        SAFE_SETUP_HOOK,
        SAFE_ENTRY_CONTEXT,
        SAFE_BACKGROUND,
    )
    for value in priority:
        if value in values:
            return value
    return ""


def _claim_temporal_llm_groups(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        record: CanonicalEvidenceRecord = entry["record"]
        key = (
            str(record.subject_id),
            str(record.boundary.get("boundary_id", "")),
        )
        grouped.setdefault(key, []).append(entry)
    return [group for _key, group in sorted(grouped.items())]


def _claim_temporal_schema() -> dict[str, Any]:
    return {
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
                        "claim_id",
                        "temporal_scope",
                        "history_eligibility",
                        "spoiler_safety",
                        "confidence",
                        "rationale",
                        "history_rationale",
                        "event_label",
                    ],
                    "properties": {
                        "claim_id": {"type": "string", "minLength": 1},
                        "temporal_scope": {
                            "type": "string",
                            "enum": list(_TEMPORAL_SCOPE_VALUES),
                        },
                        "history_eligibility": {
                            "type": "string",
                            "enum": list(_HISTORY_ELIGIBILITY_VALUES),
                        },
                        "spoiler_safety": {
                            "type": "string",
                            "enum": list(_SPOILER_SAFETY_VALUES),
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "rationale": {"type": "string", "minLength": 1, "maxLength": 260},
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
    }


def _claim_temporal_system_prompt() -> str:
    return (
        "Classify each source-side claim relative to what a player is walking into. "
        "Do not order by expansion names or wiki recency. Use the entry-state contract, source "
        "role, paragraph appearances, and outcome hints. Active outcomes and completion details "
        "are unsafe for a pre-entry player. Current roster or encounter mechanics are current "
        "evidence, but mechanics-state claims are not safe for general character-summary prose."
    )


def _claim_temporal_prompt(entries: list[dict[str, Any]]) -> str:
    first_record: CanonicalEvidenceRecord = entries[0]["record"]
    payload = {
        "active_content_boundary": _boundary_prompt_payload(first_record.boundary),
        "items": [
            {
                "claim_id": str(entry["claim"].get("claim_id", "")),
                "claim_text": str(entry["claim"].get("claim_text", "")),
                "claim_type": str(entry["claim"].get("claim_type", "")),
                "entities": entry["claim"].get("entities", []),
                "source_sentence_indexes": entry["claim"].get("source_sentence_indexes", []),
                "source_excerpt": str(entry["claim"].get("source_excerpt", "")),
                "canonical_evidence_id": str(entry["claim"].get("canonical_evidence_id", "")),
                "paragraph_scope": getattr(entry["record"].classification, "scope", ""),
                "paragraph_history_eligibility": getattr(
                    entry["record"].classification,
                    "history_eligibility",
                    "",
                ),
                "source_roles": _canonical_source_roles(entry["record"]),
                "appearances": entry["decision"].get("appearances", []),
                "deterministic_hints": entry["classification"].structural_hints,
                "fallback_rationale": entry["classification"].rationale,
            }
            for entry in entries
        ],
        "rubric": {
            "pre_entry_history": "background before the player's current entry state",
            "history_setup_bridge": "entry-state setup that explains why current content exists",
            "entry_state": "what is true as the player enters",
            "active_storyline": "setup or ongoing action the player may engage",
            "active_storyline_outcome": "resolution/completion/aftermath of active content",
            "post_active_lore": "later off-screen lore after this playable state",
            "excluded_noncanon": "non-retail/non-canon/removed source evidence",
        },
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)


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
        if contract.active_expansion is None:
            contract.active_expansion = _derive_active_expansion(rows, name=contract.name)
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
            matched_record = record_by_id.get(canonical_id)
            if matched_record is None or matched_record.classification is None:
                continue
            prior = matched_record.classification
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
        "expansion_recency": _expansion_recency(
            _paragraph_expansion_rank(record), _active_expansion_rank(record.boundary)
        ),
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
        "- active_storyline_outcome: the resolution of THIS content's own active storyline — an "
        "outcome the player brings about or witnesses by playing this instance/zone (a boss defeated "
        "here, a quest chain's payoff, a late-chain reveal). A death, defeat, failure, or shift of "
        "control that occurred off-screen or in earlier content, and whose lasting RESULT is simply "
        "the standing situation the player now finds (who holds the site, who rules, who has holed up "
        "here), is NOT this label — classify it by that standing situation, usually entry_state with "
        "history_setup_bridge, even though it names a death, defeat, or seizure.\n"
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
        "A later event does not become pre_entry_history or entry_state just because it names, "
        "visits, or interacts with the current occupants, ruler, or site. An outside faction that "
        "arrives to retrieve an artifact, negotiate, parley, or conduct research is post_active_lore "
        "even when it speaks with the current inhabitants. A contract match that only shows the "
        "paragraph mentions currently-present entities (a non-independent match) is identity "
        "context, not proof that the described event is part of the current entry state: weigh what "
        "the event IS, not merely which current entities it names.\n\n"
        "Each item includes expansion_recency, comparing the paragraph's expansion-edit section to "
        "the subject's active-content expansion: 'later' means the paragraph is from a newer "
        "expansion than the current playable content, 'earlier'/'same' older or equal, 'unknown' no "
        "signal. Treat 'later' as a soft prior toward post_active_lore unless the paragraph clearly "
        "establishes the current entry state; 'earlier'/'same' leans pre_entry/entry. This is a weak "
        "signal, not a rule — the entry-state contract and source structure still decide, and a "
        "genuinely older-but-background 'later' paragraph can still be pre_entry_history. But a "
        "paragraph marked 'later' whose contract_relation shows no linkage to the contract's active "
        "conflicts, current locations, or objectives requires strong textual evidence before you "
        "classify it as current setup (entry_state or history_setup_bridge); without that evidence "
        "prefer post_active_lore.\n\n"
        "History eligibility labels:\n"
        "- history_background: origin, fall, or background that belongs in a history card.\n"
        "- history_setup_bridge: a transition/setup paragraph that explains the current "
        "playable state, current occupants, ruler, threat, holdout, or condition as the "
        "player enters. Use this even if the paragraph also describes the current setup.\n"
        "- history_excluded_outcome: the outcome of THIS content's active storyline that the player "
        "reaches by playing it — a boss defeat or quest resolution achieved here, a late-chain "
        "reveal, or a victory/death that is the payoff of this content. Do not use it for an earlier "
        "or off-screen death, defeat, failure, or control change whose enduring result is the current "
        "holdout, ruler, or threat the player walks into; that is history_setup_bridge.\n"
        "- history_excluded_post_active: later off-screen visitors, reports, book/retrieval "
        "missions, research missions, or outside-faction activity absent from the current "
        "setup anchors.\n"
        "- history_not_applicable: not a history/background paragraph.\n\n"
        "Do not treat every later paragraph as post-active. If it explains why the current "
        "roster, controlling faction, ruler, major threat, or site condition exists when "
        "the player arrives, classify it as entry_state with history_setup_bridge. For "
        "zones, this includes transition paragraphs that explain current quest hubs, "
        "restoration efforts, faction bases, staging grounds, or front lines the player "
        "encounters on entry. Do not use history_setup_bridge for outcomes the player completes "
        "in THIS content, control changes the player's own active storyline brings about, victory "
        "summaries, or later off-screen reports. But an antagonist who, after an earlier or "
        "off-screen defeat, fell back to this site and now holds it or bides his time here IS "
        "history_setup_bridge — that is the ruler or holdout the player finds on entry, not a "
        "resolution the player achieves. Return one temporal_scope and one history_eligibility "
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
    raw_infobox = primary.get("infobox")
    infobox = cast(dict[str, Any], raw_infobox) if isinstance(raw_infobox, dict) else {}
    raw_structured_links = primary.get("structured_links")
    structured_links = (
        cast(list[Any], raw_structured_links) if isinstance(raw_structured_links, list) else []
    )
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
