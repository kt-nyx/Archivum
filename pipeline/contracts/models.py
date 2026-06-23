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


class LocationType(StrEnum):
    CITY = "city"
    STARTER_AREA = "starter_area"
    MAJOR_LOCATION = "major_location"


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
    significance: str = Field(min_length=1)
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


class EvidenceItem(BaseModel):
    source_url: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    section_role: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    raw_section_role: str | None = None
    # Provenance taxonomy (Option A): what KIND of source prose this snippet is,
    # derived from the wiki header. Drives locators independently of the
    # discovery routing `section_role`. See pipeline/common/content_role.py.
    content_role: str | None = None
    block_index: int | None = None


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
    at_a_glance: str = Field(min_length=1)
    currently: str = Field(min_length=1)
    history_sections: list[HistorySection] = Field(default_factory=list)
    major_factions: list[FactionCard] = Field(default_factory=list)
    major_questlines: list[QuestlineCardV2] = Field(default_factory=list)
    location_cards: list[LocationCard] = Field(default_factory=list)
    instance_links: list[InstanceLinkCard] = Field(default_factory=list)
    glossary_refs: list[GlossaryLink] = Field(default_factory=list)
    sources: list[SourceManifestEntry] = Field(default_factory=list)
    provenance: ZoneProvenance


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
    at_a_glance: str = Field(min_length=1)
    overview: str = Field(min_length=1)
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
        target_words=25, min_words=10, max_words=45, severity=BudgetSeverity.WARN
    ),
    "story_context": BudgetRule(
        target_words=230, min_words=170, max_words=320, severity=BudgetSeverity.HARD_FAIL
    ),
    "key_characters_card_summary": BudgetRule(
        target_words=30, min_words=18, max_words=50, severity=BudgetSeverity.WARN
    ),
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
