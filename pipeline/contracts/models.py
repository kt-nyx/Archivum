"""Canonical data contracts for lore pipeline entities.

These models are the single source of truth for MP2 schema contracts.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class BudgetSeverity(StrEnum):
    HARD_FAIL = "hard-fail"
    WARN = "warn"


class Faction(StrEnum):
    ALLIANCE = "alliance"
    HORDE = "horde"
    SHARED = "shared"


class InstanceType(StrEnum):
    DUNGEON = "dungeon"
    RAID = "raid"
    SCENARIO = "scenario"


class GlossaryCategory(StrEnum):
    PERSON = "person"
    EVENT = "event"
    ARTIFACT = "artifact"
    FACTION = "faction"
    PLACE = "place"
    CONCEPT = "concept"


class IncludeDecision(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    DEFER = "defer"


class EntityType(StrEnum):
    ZONE = "zone"
    INSTANCE = "instance"
    LOCATION = "location"
    QUEST = "quest"
    CHARACTER = "character"
    FACTION = "faction"
    GLOSSARY_TERM = "glossary_term"


class EntityKind(StrEnum):
    """Closed, domain-neutral kinds permitted at card-admission boundaries."""

    PLACE = "place"
    NAMED_ACTOR = "named_actor"
    ORGANIZATION = "organization"
    GROUP_OR_SPECIES = "group_or_species"
    OBJECT_OR_CONCEPT = "object_or_concept"
    UNKNOWN = "unknown"


class EntityKindDecision(BaseModel):
    """Evidence-bearing classification for one linked target page.

    This is deliberately distinct from :class:`EntityType`, whose values describe
    pipeline manifest rows.  A linked page is only admitted to a card family when
    this decision records the corresponding output kind.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["entity_kind_decision.v1"] = "entity_kind_decision.v1"
    decision_id: str = Field(pattern=ID_PATTERN)
    candidate_id: str = Field(pattern=ID_PATTERN)
    canonical_title: str = Field(min_length=1)
    canonical_path: str = Field(min_length=1)
    kind: EntityKind
    confidence: float = Field(ge=0.0, le=1.0)
    source_signals: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class InstanceParticipantDecision(BaseModel):
    """Admission record for one linked instance-participant candidate.

    Encounter links are leads, not character cards.  This record keeps the three
    independent facts required to admit one: target-page kind, direct presence on
    this instance page, and current retail scope.  ``encounter_relation`` remains
    descriptive evidence and never substitutes for either admission fact.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    canonical_path: str = Field(min_length=1)
    entity_kind_decision_id: str = Field(min_length=1)
    entity_kind: EntityKind
    instance_presence_evidence: list[str] = Field(default_factory=list)
    retail_scope: Literal["retail_confirmed", "non_retail", "unknown"]
    retail_scope_evidence: list[str] = Field(default_factory=list)
    encounter_relation_evidence: list[str] = Field(default_factory=list)
    admission: Literal["eligible", "rejected"]
    reason_codes: list[str] = Field(default_factory=list)
    final_selection_reason: str | None = None
    final_role: Literal["ally", "enemy", "neutral", "uncertain"] = "uncertain"
    emitted: bool = False


class InstanceKeyCharacterDecision(BaseModel):
    """The one auditable key-character decision for an instance page."""

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(pattern=ID_PATTERN)
    candidates: list[InstanceParticipantDecision] = Field(default_factory=list)


class InstanceKeyCharacterDecisionArtifact(BaseModel):
    """Clean-break sidecar consumed by render checks and instance reports."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["instance_key_character_decision.v1"] = (
        "instance_key_character_decision.v1"
    )
    producer: Literal["draft_writer"] = "draft_writer"
    decisions: list[InstanceKeyCharacterDecision] = Field(default_factory=list)


class LocationType(StrEnum):
    CITY = "city"
    TOWN = "town"
    STARTER_AREA = "starter_area"
    FORTRESS = "fortress"
    RUINS = "ruins"
    LANDMARK = "landmark"
    OUTPOST = "outpost"
    NATURAL_FEATURE = "natural_feature"
    MAJOR_LOCATION = "major_location"


class LocationSelectionState(StrEnum):
    """Lifecycle states for a directly-evidenced location card candidate."""

    CANDIDATE = "candidate"
    PROBE = "probe"
    PROFILE = "profile"
    SELECTED = "selected"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class LocationSelectionDecision(BaseModel):
    """One auditable location-discovery decision.

    A decision's ``location_id`` is also the only acceptable subject identity for
    its profile evidence.  This deliberately makes a name/substring join
    impossible at the rendering boundary.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["location_selection_decision.v1"] = "location_selection_decision.v1"
    decision_id: str = Field(pattern=ID_PATTERN)
    zone_id: str = Field(pattern=ID_PATTERN)
    location_id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    source_link: str = Field(min_length=1)
    source_relation: str = "other"
    candidate_rank: int = Field(ge=0)
    state: LocationSelectionState
    entity_kind: EntityKind = EntityKind.UNKNOWN
    entity_kind_decision_id: str = ""
    source_ids: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    infobox: dict[str, str] = Field(default_factory=dict)
    zone_record: Literal["on_zone", "off_zone", "unknown"] = "unknown"
    profile_source_id: str = ""
    profile_evidence_count: int = Field(default=0, ge=0)
    reason_codes: list[str] = Field(default_factory=list)


class LocationCoverageStatus(BaseModel):
    """Per-zone bounded-retrieval result for the location-card family."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(pattern=ID_PATTERN)
    desired_card_count: int = Field(ge=1)
    selected_count: int = Field(ge=0)
    probe_cap: int = Field(ge=1)
    profile_cap: int = Field(ge=1)
    probes_attempted: int = Field(ge=0)
    profiles_attempted: int = Field(ge=0)
    status: Literal["coverage_met", "insufficient_viable_locations"]
    attempted_candidate_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class LocationSelectionArtifact(BaseModel):
    """Clean-break, versioned location selection handoff."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["location_selection.v1"] = "location_selection.v1"
    producer: Literal["discovery", "traverse_seed"]
    decisions: list[LocationSelectionDecision] = Field(default_factory=list)
    coverage: list[LocationCoverageStatus] = Field(default_factory=list)


class RetailEligibility(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE_CLASSIC_ONLY = "ineligible_classic_only"
    INELIGIBLE_OTHER_GAME = "ineligible_other_game"
    UNKNOWN = "unknown"


class DisambiguationState(StrEnum):
    NONE = "none"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class BudgetRule(BaseModel):
    """Word budget contract for a section/card payload."""

    target_words: int
    min_words: int
    max_words: int
    severity: BudgetSeverity


class SourcePointer(BaseModel):
    """Strict-four source pointer required for provenance."""

    source_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    excerpt_hash: str = Field(min_length=1)


class SourceManifestEntry(BaseModel):
    source_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    revision_id: str | None = None


class CanonicalEntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(pattern=ID_PATTERN)
    entity_type: EntityType
    wiki_title: str = Field(min_length=1)
    wiki_url: str = Field(min_length=1)
    page_id: int | None = None
    redirect_chain: list[str] = Field(default_factory=list)
    disambiguation_state: DisambiguationState = DisambiguationState.NONE
    retail_eligibility: RetailEligibility = RetailEligibility.UNKNOWN


class HistorySection(BaseModel):
    heading: str = Field(min_length=1)
    body: str = Field(min_length=1)
    source_refs: list[SourcePointer] = Field(default_factory=list)


class FactionCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    wiki_url: str = Field(min_length=1)


class LocationCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    location_type: LocationType
    zone_id: str = Field(pattern=ID_PATTERN)
    wiki_url: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    significance_tag: str = Field(min_length=1)
    decision_reason_codes: list[str] = Field(default_factory=list)
    ui_hints: dict[str, str] = Field(default_factory=dict)
    provenance: list[SourcePointer] = Field(default_factory=list)


class QuestlineCardV2(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1)
    faction: Faction
    cta_hook: str = Field(min_length=1)
    start_anchor: str = Field(min_length=1)
    chain_refs: list[str] = Field(default_factory=list)
    include_decision: IncludeDecision
    reason_codes: list[str] = Field(default_factory=list)
    wiki_refs: list[str] = Field(default_factory=list)


class QuestlineCardMetadata(BaseModel):
    """The one discovery-to-draft contract for a selected questline card.

    ``chain_refs`` is deliberately the only name for the ordered, rendered
    portion of a chain.  Any remaining graph members belong in
    ``overflow_chain_refs``; readers must never reconstruct either list from
    a second discovery artifact.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["questline_card_metadata.v1"] = "questline_card_metadata.v1"
    metadata_id: str = Field(pattern=ID_PATTERN)
    zone_id: str = Field(pattern=ID_PATTERN)
    cluster_id: str = Field(pattern=ID_PATTERN)
    source_arc_id: str = Field(pattern=ID_PATTERN)
    card_id: str = Field(pattern=ID_PATTERN)
    display_title: str = Field(min_length=1)
    faction: str = Field(min_length=1)
    faction_variant: str | None = None
    phase_variant: str | None = None
    segment_index: int = Field(default=1, ge=1)
    start_anchor: str = Field(min_length=1)
    start_anchor_ref: str = Field(pattern=ID_PATTERN)
    chain_refs: list[str] = Field(min_length=1)
    overflow_chain_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    algorithm_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_chain_contract(self) -> QuestlineCardMetadata:
        if self.start_anchor_ref not in self.chain_refs + self.overflow_chain_refs:
            raise ValueError("start_anchor_ref must belong to the serialized quest chain")
        refs = self.chain_refs + self.overflow_chain_refs
        if len(refs) != len(set(refs)):
            raise ValueError("questline metadata chain refs must be unique")
        return self


class QuestlineCardMetadataArtifact(BaseModel):
    """Versioned, fail-fast questline metadata handoff written by discovery."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["questline_card_metadata.v1"] = "questline_card_metadata.v1"
    producer: Literal["discovery.questline_card_polish"] = "discovery.questline_card_polish"
    metadata: list[QuestlineCardMetadata] = Field(default_factory=list)


class DecisionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1)
    subject_type: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)
    features: dict[str, float | int | str | bool] = Field(default_factory=dict)
    hard_reject: bool = False
    hard_reject_reasons: list[str] = Field(default_factory=list)
    score: float | None = None
    thresholds: dict[str, float] = Field(default_factory=dict)
    borderline_adjudication: dict[str, str] | None = None
    final_decision: IncludeDecision
    reason_codes: list[str] = Field(default_factory=list)
    significance_tag: str | None = None
    temporal_scope: str | None = None
    temporal_reason: str | None = None


class EvidenceLink(BaseModel):
    """One inline article link carried over from an evidence snippet's source block."""

    anchor_text: str = ""
    href: str = Field(min_length=1)


class EvidenceItem(BaseModel):
    source_url: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    section_role: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    # Slice 12: the source block's own inline article links (document order,
    # deduped per block; empty when the paragraph has none).
    links: list[EvidenceLink] = Field(default_factory=list)
    raw_section_role: str | None = None
    # Provenance taxonomy (Option A): what KIND of source prose this snippet is,
    # derived from the wiki header. Drives locators independently of the
    # discovery routing `section_role`. See pipeline/common/content_role.py.
    content_role: str | None = None
    block_index: int | None = None
    canonical_evidence_id: str | None = None
    temporal_scope: str | None = None
    temporal_confidence: float | None = Field(default=None, ge=0, le=1)
    temporal_reason: str | None = None
    temporal_event_label: str | None = None
    history_eligibility: str | None = None
    history_reason: str | None = None


class EvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1)
    subject_type: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    constraints: dict[str, str | int | bool] = Field(default_factory=dict)
    build_meta: dict[str, str] = Field(default_factory=dict)


class QuestRecord(BaseModel):
    """Structured per-quest record extracted from the wiki Questbox parse tree.

    Produced during quest traversal (Slice A) and consumed by clustering /
    significance / anchor stages downstream. Most narrative fields are optional
    because wiki Questbox completeness varies by quest and expansion.
    """

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    quest_title: str = Field(min_length=1)
    source_link: str = Field(min_length=1)
    has_questbox: bool = True
    start_npc: str = ""
    start_location: str = ""
    start_coords: str = ""
    end_npc: str = ""
    category: str = ""
    reputation_org: str = ""
    faction: Faction = Faction.SHARED
    previous: list[str] = Field(default_factory=list)
    next: list[str] = Field(default_factory=list)
    faction_mirror: list[str] = Field(default_factory=list)
    description: str = ""


class QuestlineClusterSummary(BaseModel):
    """Cluster-level summary produced by post-traverse questline clustering (Slice B)."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    cluster_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    faction: Faction = Faction.SHARED
    quest_count: int = Field(ge=0)
    reputation_orgs: list[str] = Field(default_factory=list)
    quest_node_ids: list[str] = Field(default_factory=list)
    algorithm_version: str = Field(default="v1-prereq-graph")
    unresolved_edge_count: int = Field(default=0, ge=0)


class InclusionDecision(BaseModel):
    """Inclusion/exclusion audit object used in candidate filtering."""

    inclusion_score: int = Field(ge=0, le=12)
    criteria_breakdown: dict[str, int]
    include_decision: IncludeDecision
    decision_reason: str = Field(min_length=1)
    source_refs: list[SourcePointer] = Field(default_factory=list)

    @field_validator("criteria_breakdown")
    @classmethod
    def validate_breakdown_scores(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("criteria_breakdown must include at least one criterion")
        if any(score < 0 or score > 2 for score in value.values()):
            raise ValueError("criteria_breakdown values must be in range 0..2")
        return value

    @model_validator(mode="after")
    def inclusion_score_matches_criteria_total(self) -> InclusionDecision:
        expected = sum(self.criteria_breakdown.values())
        if self.inclusion_score != expected:
            raise ValueError(
                "inclusion_score must equal the sum of criteria_breakdown values "
                f"(got score {self.inclusion_score}, sum {expected})"
            )
        return self


class CharacterCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    role: Literal["enemy", "ally", "neutral", "uncertain"] = "uncertain"
    wiki_ref: str | None = None
    decision_reason_codes: list[str] = Field(default_factory=list)
    thumbnail_asset_id: str | None = None


class LandmarkCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    thumbnail_asset_id: str | None = None
    significance_tag: str | None = None


class InstanceLinkCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    thumbnail_asset_id: str | None = None


class GlossaryLink(BaseModel):
    term_id: str = Field(pattern=ID_PATTERN)
    label: str | None = None
    wiki_url: str | None = None


class QuestlineCard(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    faction: Faction
    title: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    start_anchor: str = Field(min_length=1)
    story_beats: list[str] = Field(default_factory=list, max_length=3)
    parallel_arc_key: str | None = None
    inclusion_decision: InclusionDecision
    depends_on_parent_context: bool = False
    dependency_note: str | None = None


class ZoneProvenance(BaseModel):
    at_a_glance: list[SourcePointer] = Field(default_factory=list)
    currently: list[SourcePointer] = Field(default_factory=list)
    history: list[SourcePointer] = Field(default_factory=list)
    major_questlines_alliance: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_questlines_horde: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_questlines_shared: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_characters: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_factions: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    instances: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_landmarks: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    glossary: dict[str, list[SourcePointer]] = Field(default_factory=dict)


class ZonePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    wiki_url: str = Field(min_length=1)
    parent_continent: str = Field(min_length=1)
    expansion_context: str = Field(min_length=1)
    # Prose fields are nullable: a field whose live synthesis fails after retries is emitted as
    # null with the reason recorded in ``field_status`` — never as borrowed source text.
    at_a_glance: str | None = Field(default=None, min_length=1)
    currently: str | None = Field(default=None, min_length=1)
    history_sections: list[HistorySection] = Field(default_factory=list)
    major_factions: list[FactionCard] = Field(default_factory=list)
    major_questlines: list[QuestlineCardV2] = Field(default_factory=list)
    location_cards: list[LocationCard] = Field(default_factory=list)
    instance_links: list[InstanceLinkCard] = Field(default_factory=list)
    glossary_refs: list[GlossaryLink] = Field(default_factory=list)
    sources: list[SourceManifestEntry] = Field(default_factory=list)
    provenance: ZoneProvenance
    # Per-field outcome map ("ok" | "synthesis_failed" | "no_evidence" | "offline_fallback");
    # the validate stage treats a null field with a recorded failure as a status, not an error.
    field_status: dict[str, str] = Field(default_factory=dict)


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    slug: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    expansion: str = Field(min_length=1)
    at_a_glance: str = Field(min_length=1)
    currently: str = Field(min_length=1)
    history: str = Field(min_length=1)
    major_questlines_alliance: list[QuestlineCard] = Field(default_factory=list)
    major_questlines_horde: list[QuestlineCard] = Field(default_factory=list)
    major_questlines_shared: list[QuestlineCard] = Field(default_factory=list)
    major_characters: list[CharacterCard]
    instances: list[InstanceLinkCard]
    major_landmarks: list[LandmarkCard]
    glossary: list[GlossaryLink]
    sources: list[SourceManifestEntry]
    provenance: ZoneProvenance

    map_id: int | None = None
    faction_notes: str | None = None
    timeline_start: str | None = None
    timeline_end: str | None = None
    media_assets: list[str] = Field(default_factory=list)
    editorial_notes: str | None = None
    future_player_progress_hooks: list[str] = Field(default_factory=list)


class SubZoneProvenance(BaseModel):
    at_a_glance: list[SourcePointer] = Field(default_factory=list)
    currently: list[SourcePointer] = Field(default_factory=list)
    history: list[SourcePointer] = Field(default_factory=list)
    major_questlines_alliance: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_questlines_horde: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_questlines_shared: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_characters: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    instances: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_landmarks: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    glossary: dict[str, list[SourcePointer]] = Field(default_factory=dict)


class SubZone(BaseModel):
    """Contract for sub-zone micro pages (section 15 locked policy)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    slug: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    parent_zone_id: str = Field(pattern=ID_PATTERN)
    at_a_glance: str = Field(min_length=1)
    currently: str = Field(min_length=1)
    history: str = Field(min_length=1)
    major_characters: list[CharacterCard]
    major_landmarks: list[LandmarkCard]
    glossary: list[GlossaryLink]
    sources: list[SourceManifestEntry]
    provenance: SubZoneProvenance

    major_questlines_alliance: list[QuestlineCard] = Field(default_factory=list)
    major_questlines_horde: list[QuestlineCard] = Field(default_factory=list)
    major_questlines_shared: list[QuestlineCard] = Field(default_factory=list)
    instances: list[InstanceLinkCard] = Field(default_factory=list)
    expansion: str | None = None
    map_id: int | None = None


class ZoneBacklink(BaseModel):
    zone_id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1)


class InstanceProvenance(BaseModel):
    identity_header: list[SourcePointer] = Field(default_factory=list)
    story_context: list[SourcePointer] = Field(default_factory=list)
    key_characters: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    major_factions: dict[str, list[SourcePointer]] = Field(default_factory=dict)
    glossary: dict[str, list[SourcePointer]] = Field(default_factory=dict)


class InstancePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    instance_type: Literal["raid", "dungeon"]
    parent_zone_id: str = Field(pattern=ID_PATTERN)
    expansion_context: str = Field(min_length=1)
    wiki_url: str = Field(min_length=1)
    # Nullable prose + field_status: see ZonePage — failed live synthesis is null + status,
    # never borrowed source text.
    at_a_glance: str | None = Field(default=None, min_length=1)
    overview: str | None = Field(default=None, min_length=1)
    history_sections: list[HistorySection] = Field(default_factory=list)
    key_characters: list[CharacterCard] = Field(default_factory=list)
    major_factions: list[FactionCard] = Field(default_factory=list)
    lore_source: Literal["instance_page", "linked_lore_page"] = "instance_page"
    lore_source_reason: str | None = None
    variant_policy: Literal["standalone", "merged_variant"] = "standalone"
    variant_reason_codes: list[str] = Field(default_factory=list)
    glossary_refs: list[GlossaryLink] = Field(default_factory=list)
    sources: list[SourceManifestEntry] = Field(default_factory=list)
    provenance: InstanceProvenance
    field_status: dict[str, str] = Field(default_factory=dict)


class Instance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    slug: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    type: InstanceType
    zone_id: str = Field(pattern=ID_PATTERN)
    identity_header: str = Field(min_length=1)
    story_context: str = Field(min_length=1)
    key_characters: list[CharacterCard]
    zone_backlink: ZoneBacklink
    glossary: list[GlossaryLink]
    sources: list[SourceManifestEntry]
    provenance: InstanceProvenance

    expansion: str | None = None
    wing_count: int | None = Field(default=None, ge=1)
    version_notes: str | None = None
    related_factions: list[str] = Field(default_factory=list)
    media_assets: list[str] = Field(default_factory=list)


class CharacterProvenance(BaseModel):
    summary: list[SourcePointer] = Field(default_factory=list)
    short_history: list[SourcePointer] = Field(default_factory=list)


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    slug: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    short_history: str = Field(min_length=1)
    glossary: list[GlossaryLink]
    sources: list[SourceManifestEntry]
    provenance: CharacterProvenance

    titles: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    media_assets: list[str] = Field(default_factory=list)
    status_hint: str | None = None


class GlossaryFacets(BaseModel):
    model_config = ConfigDict(extra="allow")


class GlossaryTermProvenance(BaseModel):
    summary: list[SourcePointer] = Field(default_factory=list)
    brief_history: list[SourcePointer] = Field(default_factory=list)


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    slug: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1)
    category: GlossaryCategory
    aliases: list[str]
    summary: str = Field(min_length=1)
    brief_history: str = Field(min_length=1)
    sources: list[SourceManifestEntry]
    provenance: GlossaryTermProvenance

    facets: GlossaryFacets | None = None
    timeline_hint: str | None = None
    expansion_tags: list[str] = Field(default_factory=list)
    ambiguity_notes: str | None = None
    related_terms: list[str] = Field(default_factory=list)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for alias in value:
            cleaned = alias.strip().lower()
            if not cleaned:
                raise ValueError("aliases cannot include empty values")
            if not re.fullmatch(r"[a-z0-9][a-z0-9\s'\-]*", cleaned):
                raise ValueError("aliases must be normalized lowercase text")
            normalized.append(cleaned)
        if len(set(normalized)) != len(normalized):
            raise ValueError("aliases must be unique when normalized")
        return normalized


class AssetProvenance(BaseModel):
    caption: list[SourcePointer] = Field(default_factory=list)
    metadata: list[SourcePointer] = Field(default_factory=list)


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    asset_type: Literal["image", "icon", "model_ref"]
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    license: str = Field(min_length=1)
    credit: str = Field(min_length=1)
    allowed_use: bool
    allowed_use_reason: str = Field(min_length=1)
    proof_ref: str = Field(min_length=1)
    associated_entity_ids: list[str] = Field(default_factory=list)
    sources: list[SourceManifestEntry]
    provenance: AssetProvenance

    caption: str | None = None
    crop_hint: str | None = None
    locale: str | None = None
    internal_notes: str | None = None


ZONE_BUDGET_RULES: dict[str, BudgetRule] = {
    "at_a_glance": BudgetRule(
        target_words=35, min_words=20, max_words=60, severity=BudgetSeverity.WARN
    ),
    "currently": BudgetRule(
        target_words=110, min_words=80, max_words=140, severity=BudgetSeverity.HARD_FAIL
    ),
    "history": BudgetRule(
        target_words=220, min_words=140, max_words=400, severity=BudgetSeverity.HARD_FAIL
    ),
    "major_questlines_card_hook": BudgetRule(
        target_words=70,
        min_words=45,
        max_words=100,
        severity=BudgetSeverity.HARD_FAIL,
    ),
    "major_characters_card_summary": BudgetRule(
        target_words=28,
        min_words=18,
        max_words=45,
        severity=BudgetSeverity.WARN,
    ),
    "instances_card_summary": BudgetRule(
        target_words=30, min_words=18, max_words=50, severity=BudgetSeverity.WARN
    ),
    "major_landmarks_card_summary": BudgetRule(
        target_words=32,
        min_words=20,
        max_words=50,
        severity=BudgetSeverity.WARN,
    ),
}

INSTANCE_BUDGET_RULES: dict[str, BudgetRule] = {
    "identity_header": BudgetRule(
        target_words=37, min_words=22, max_words=55, severity=BudgetSeverity.WARN
    ),
    "story_context": BudgetRule(
        target_words=105, min_words=70, max_words=160, severity=BudgetSeverity.HARD_FAIL
    ),
    # Sized for who-they-are -> biography -> why-they're-here, now that spoiler-safe backstory and
    # the motivation hook actually reach synthesis. The floor stays low so a genuinely thin figure
    # (structural-presence blurb) still ships; the synthesizer's target is capped per-card at what
    # the evidence supports (see key_characters._run_validated), so the raised ceiling grows rich
    # cards without padding thin ones.
    "key_characters_card_summary": BudgetRule(
        target_words=80, min_words=25, max_words=115, severity=BudgetSeverity.WARN
    ),
}

# Page-scope budget rules (Slice 2): the single home for the word budgets that the
# published zone_page / instance_page payloads are validated against. The draft-side lint
# constants derive from these and validate reads them directly, so the two sides cannot
# drift apart again. History sections use one shared rule for both page types.
PAGE_HISTORY_SECTION_BUDGET_RULE = BudgetRule(
    target_words=75, min_words=40, max_words=110, severity=BudgetSeverity.HARD_FAIL
)

ZONE_PAGE_BUDGET_RULES: dict[str, BudgetRule] = {
    "at_a_glance": BudgetRule(
        target_words=33, min_words=18, max_words=48, severity=BudgetSeverity.WARN
    ),
    "currently": BudgetRule(
        target_words=60, min_words=35, max_words=90, severity=BudgetSeverity.HARD_FAIL
    ),
    "major_factions_card_summary": BudgetRule(
        target_words=30, min_words=18, max_words=48, severity=BudgetSeverity.WARN
    ),
    # The zone's instance-link card reuses the instance page's own at_a_glance caption
    # (draft_writer.instance_summary_map), so it shares that caption's budget — a smaller
    # cap here would only hard-trim the caption mid-sentence.
    "instance_links_card_summary": INSTANCE_BUDGET_RULES["identity_header"],
}

CHARACTER_BUDGET_RULES: dict[str, BudgetRule] = {
    "summary": BudgetRule(
        target_words=70, min_words=45, max_words=100, severity=BudgetSeverity.HARD_FAIL
    ),
    "short_history": BudgetRule(
        target_words=110, min_words=70, max_words=160, severity=BudgetSeverity.HARD_FAIL
    ),
}

GLOSSARY_BUDGET_RULES: dict[str, BudgetRule] = {
    "summary": BudgetRule(
        target_words=60, min_words=35, max_words=90, severity=BudgetSeverity.HARD_FAIL
    ),
    "brief_history": BudgetRule(
        target_words=115, min_words=70, max_words=170, severity=BudgetSeverity.HARD_FAIL
    ),
}

ZONE_MIN_TOTAL_QUESTLINE_CARDS = 2
ZONE_MAX_TOTAL_QUESTLINE_CARDS = 6
ZONE_MAX_TOTAL_QUESTLINE_WORDS = 480
ZONE_MIN_MAJOR_CHARACTERS = 3
ZONE_MAX_MAJOR_CHARACTERS = 6
ZONE_MIN_MAJOR_LANDMARKS = 3
ZONE_MAX_MAJOR_LANDMARKS = 8
INSTANCE_MIN_KEY_CHARACTERS = 2
INSTANCE_MAX_KEY_CHARACTERS = 10
# Max provenance pointers per instance section/card. WARN by default, HARD_FAIL at the
# release gate; single source of truth shared by validate and check_run_semantics.
INSTANCE_PROVENANCE_POINTER_CAP = 3
CHARACTER_MAX_PAGE_WORDS = 200
SUB_ZONE_MAX_QUESTLINE_CARDS = 3
ZONE_MIN_QUESTLINE_INCLUSION_SCORE = 8
SUB_ZONE_MIN_QUESTLINE_INCLUSION_SCORE = 9


def required_pointer_count(word_count: int) -> int:
    """Recommended provenance pointers for a prose section of ``word_count`` words.

    Single home (Slice 7) shared by the draft-side citation retry reason and validate's
    provenance rule. A shortfall against this count is a WARN, never grounds to fabricate
    pointers: draft ships the real (short) pointer list and records the shortfall.
    """
    if word_count <= 120:
        return 1
    if word_count <= 240:
        return 2
    return 3

ENTITY_MODEL_MAP: dict[str, type[BaseModel]] = {
    "zone": Zone,
    "sub_zone": SubZone,
    "instance": Instance,
    "character": Character,
    "glossary_term": GlossaryTerm,
    "asset": Asset,
}

WIKI_FIRST_ENTITY_MODEL_MAP: dict[str, type[BaseModel]] = {
    "zone_page": ZonePage,
    "instance_page": InstancePage,
    "location_card": LocationCard,
    "canonical_entity_ref": CanonicalEntityRef,
    "decision_artifact": DecisionArtifact,
    "evidence_pack": EvidencePack,
    "quest_record": QuestRecord,
    "questline_cluster_summary": QuestlineClusterSummary,
}
