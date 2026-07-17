"""Slice 9, item 1: consolidated cross-cutting behavioral regression surface.

One compact synthetic fixture per cross-cutting behavior, exercised through the real public entry
point, with the adversarial case the cross-cutting fixture policy requires: ambiguous entity pages,
untyped links, containment inversion, a generic term linked inside an encounter section, parallel
faction arcs, repeated title decoration, missing metadata refs, and malformed generated clauses.

Every fixture uses invented names and structures (the tests' "Fake Vale / Archive Vault /
Archivist Maelor" convention). No pilot output (WPL, Desolace, Scholomance, Maraudon, Westfall) is
encoded as a prescribed answer. Deeper per-slice tests live alongside each slice; this module is the
single durable regression surface the pilot cycle re-runs.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline.contracts.models import (
    ArcCandidate,
    ArcFamily,
    ArcFamilyDecision,
    EntityKind,
    QuestlineArcSelectionArtifact,
    QuestlineCardMetadata,
)
from pipeline.discovery.entity_typing import decide_entity_kind
from pipeline.discovery.instance_bosses import is_direct_instance_participant_section
from pipeline.discovery.questline_card_polish import render_questline_title
from pipeline.discovery.questline_significance import select_zone_arc_families
from pipeline.generate.draft.card_evidence_pack import build_card_evidence_pack, pack_is_sufficient
from pipeline.generate.draft.card_lint import finalize_cta_hook, lint_cta_hook

ZONE_ID = "zone-fake-vale"


# ---------------------------------------------------------------------------
# Behavior 1 — entity-kind admission
# ---------------------------------------------------------------------------


def _snapshot(*, categories: list[str] | None = None, infobox: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "source_id": "src-fake-1",
        "categories": categories or [],
        "infobox": infobox or {},
        "section_blocks": [],
    }


def test_entity_kind_admits_place_named_actor_group_and_concept() -> None:
    place = decide_entity_kind(
        candidate_id="location-stillwater-rest",
        canonical_title="Stillwater Rest",
        canonical_path="/wiki/Stillwater_Rest",
        source_snapshot=_snapshot(categories=["Fake Vale locations"]),
    )
    actor = decide_entity_kind(
        candidate_id="character-archivist-maelor",
        canonical_title="Archivist Maelor",
        canonical_path="/wiki/Archivist_Maelor",
        source_snapshot=_snapshot(categories=["Fake Vale NPCs"]),
    )
    species = decide_entity_kind(
        candidate_id="group-sand-lurkers",
        canonical_title="Sand Lurker",
        canonical_path="/wiki/Sand_Lurker",
        source_snapshot=_snapshot(categories=["Vale creature types"]),
    )
    concept = decide_entity_kind(
        candidate_id="object-sealed-ward",
        canonical_title="Sealed Ward",
        canonical_path="/wiki/Sealed_Ward",
        source_snapshot=_snapshot(infobox={"type": "ability"}),
    )
    assert place.kind is EntityKind.PLACE
    assert actor.kind is EntityKind.NAMED_ACTOR
    assert species.kind is EntityKind.GROUP_OR_SPECIES
    assert concept.kind is EntityKind.OBJECT_OR_CONCEPT


def test_entity_kind_abstains_on_untyped_link_and_conflicting_evidence() -> None:
    # Adversarial: an untyped link (no categories, no infobox) is never promoted to a render kind.
    untyped = decide_entity_kind(
        candidate_id="unknown-thing",
        canonical_title="Whispering Thing",
        canonical_path="/wiki/Whispering_Thing",
        source_relation="linked_from_zone",
    )
    # Adversarial: a structurally ambiguous page (place + concept category families) abstains.
    ambiguous = decide_entity_kind(
        candidate_id="ambiguous-rite",
        canonical_title="Ritual Basin",
        canonical_path="/wiki/Ritual_Basin",
        source_snapshot=_snapshot(categories=["Fake Vale locations", "Concepts"]),
    )
    assert untyped.kind is EntityKind.UNKNOWN
    assert "insufficient_target_evidence" in untyped.reason_codes
    assert ambiguous.kind is EntityKind.UNKNOWN
    assert "conflicting_target_evidence" in ambiguous.reason_codes


# ---------------------------------------------------------------------------
# Behavior 2/3 — direct evidence ownership and containment direction
# ---------------------------------------------------------------------------


def _identity_item(evidence_id: str, snippet: str) -> dict[str, Any]:
    return {"canonical_evidence_id": evidence_id, "source_id": "src-fake-1", "snippet": snippet}


def test_direct_identity_evidence_is_required_and_owned() -> None:
    pack = build_card_evidence_pack(
        card_id="location-stillwater-rest",
        card_type="location",
        subject_id="location-stillwater-rest",
        subject_name="Stillwater Rest",
        identity_items=[
            _identity_item("ev-1", "Stillwater Rest is a fortified waystation on the northern road.")
        ],
    )
    assert pack_is_sufficient(pack)
    assert [ref.evidence_id for ref in pack.identity_evidence] == ["ev-1"]
    assert pack.provenance_ids == ["ev-1"]


def test_mention_only_evidence_cannot_establish_identity() -> None:
    # Adversarial (containment inversion): the only evidence is a mention owned by another subject.
    pack = build_card_evidence_pack(
        card_id="location-stillwater-rest",
        card_type="location",
        subject_id="location-stillwater-rest",
        subject_name="Stillwater Rest",
        identity_items=[],
        relationship_items=[
            {
                "canonical_evidence_id": "ev-vale-2",
                "source_id": "src-fake-2",
                "location_id": "location-fake-vale",
                "snippet": "Fake Vale contains the waystation at Stillwater Rest.",
            }
        ],
    )
    assert not pack_is_sufficient(pack)
    assert pack.identity_evidence == []
    assert len(pack.relationship_evidence) == 1
    relation = pack.relationship_evidence[0]
    assert relation.direction == "mentions_subject"
    # Direction preserved: the container (Fake Vale) is the owner, not the card subject.
    assert relation.owner_subject_id == "location-fake-vale"


# ---------------------------------------------------------------------------
# Behavior 4 — named instance participation
# ---------------------------------------------------------------------------


def test_only_roster_shaped_sections_prove_instance_participation() -> None:
    assert is_direct_instance_participant_section("bosses")
    assert is_direct_instance_participant_section("dungeon_journal")
    assert is_direct_instance_participant_section("encounters_edit")
    # Adversarial: a generic term linked inside overview/lore prose is a lead, not participation.
    assert not is_direct_instance_participant_section("overview")
    assert not is_direct_instance_participant_section("lore")


def test_generic_type_link_is_not_admitted_as_named_participant() -> None:
    # A creature type linked inside a boss section still fails the named_actor kind gate.
    generic = decide_entity_kind(
        candidate_id="group-centaur",
        canonical_title="Centaur",
        canonical_path="/wiki/Centaur",
        source_snapshot=_snapshot(categories=["Playable races"]),
    )
    assert generic.kind is EntityKind.GROUP_OR_SPECIES


# ---------------------------------------------------------------------------
# Behavior 5 — questline metadata handoff contract
# ---------------------------------------------------------------------------


def _metadata_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        metadata_id="metadata-sealed-gate-1",
        zone_id=ZONE_ID,
        cluster_id="cluster-sealed-gate",
        source_arc_id="arc-sealed-gate",
        card_id="cluster-sealed-gate",
        canonical_id="cluster-sealed-gate",
        base_title="The Sealed Gate",
        faction="alliance",
        start_anchor="A Vigil Begins",
        start_anchor_ref="quest-vigil",
        chain_refs=["quest-vigil", "quest-seal"],
        algorithm_version="arc-v1",
    )
    base.update(overrides)
    return base


def test_questline_metadata_contract_accepts_valid_handoff() -> None:
    metadata = QuestlineCardMetadata(**_metadata_kwargs())
    assert metadata.chain_refs[0] == metadata.start_anchor_ref


def test_questline_metadata_contract_rejects_broken_handoffs() -> None:
    # Adversarial: start anchor not in the serialized chain.
    with pytest.raises(ValueError):
        QuestlineCardMetadata(**_metadata_kwargs(start_anchor_ref="quest-missing"))
    # Adversarial: duplicate chain refs.
    with pytest.raises(ValueError):
        QuestlineCardMetadata(
            **_metadata_kwargs(chain_refs=["quest-vigil", "quest-vigil"], start_anchor_ref="quest-vigil")
        )
    # Adversarial: canonical id disagreeing with card id.
    with pytest.raises(ValueError):
        QuestlineCardMetadata(**_metadata_kwargs(canonical_id="cluster-other"))


# ---------------------------------------------------------------------------
# Behavior 6 — arc-family / variant selection
# ---------------------------------------------------------------------------


def _quest_record(node_id: str, *, hub: str = "", npc: str = "", nxt: list[str] | None = None, prev: list[str] | None = None) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "zone_id": ZONE_ID,
        "start_location": hub,
        "start_npc": npc,
        "description": "The order defends the vale bridge against raiders storming the causeway.",
        "previous": prev or [],
        "next": nxt or [],
    }


def _cluster(cluster_id: str, title: str, faction: str, node_ids: list[str]) -> dict[str, Any]:
    return {"cluster_id": cluster_id, "zone_id": ZONE_ID, "title": title, "faction": faction, "quest_node_ids": node_ids}


def _v3_rows(node_ids_by_cluster: dict[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {"zone_id": ZONE_ID, "node_type": "quest", "cluster_id": cluster_id, "title": node_id}
        for cluster_id, node_ids in node_ids_by_cluster.items()
        for node_id in node_ids
    ]


def test_parallel_faction_arcs_merge_into_one_family_with_both_variants() -> None:
    clusters = [
        _cluster("cluster-defense-alliance", "Defense of the Vale", "alliance", ["q-a1", "q-a2"]),
        _cluster("cluster-defense-horde", "Defense of the Vale", "horde", ["q-b1", "q-b2"]),
        _cluster("cluster-causeway", "The Broken Causeway", "shared", ["q-c1", "q-c2"]),
    ]
    quest_records = [
        _quest_record("q-a1", hub="Vale Watch", npc="Captain Reed", nxt=["q-a2"]),
        _quest_record("q-a2", hub="Vale Watch", npc="Captain Reed", prev=["q-a1"]),
        _quest_record("q-b1", hub="Vale Watch", npc="Captain Reed", nxt=["q-b2"]),
        _quest_record("q-b2", hub="Vale Watch", npc="Captain Reed", prev=["q-b1"]),
        _quest_record("q-c1", hub="Old Causeway", npc="Scout Vell", nxt=["q-c2"]),
        _quest_record("q-c2", hub="Old Causeway", npc="Scout Vell", prev=["q-c1"]),
    ]
    v3_rows = _v3_rows(
        {
            "cluster-defense-alliance": ["q-a1", "q-a2"],
            "cluster-defense-horde": ["q-b1", "q-b2"],
            "cluster-causeway": ["q-c1", "q-c2"],
        }
    )
    candidates, families, _decisions, selected = select_zone_arc_families(
        zone_id=ZONE_ID,
        cluster_summaries=clusters,
        v3_rows=v3_rows,
        quest_records=quest_records,
    )
    # The two same-title faction clusters collapse into one family; the distinct campaign is its own.
    family_member_counts = sorted(len(family["candidate_ids"]) for family in families)
    assert family_member_counts == [1, 2]
    # Both faction variants are selected — a counterpart is never silently dropped.
    assert set(selected) == {"cluster-defense-alliance", "cluster-defense-horde", "cluster-causeway"}


def test_single_quest_weak_fragment_is_excluded() -> None:
    clusters = [_cluster("cluster-stray", "A Stray Errand", "shared", ["q-x1"])]
    quest_records = [_quest_record("q-x1")]  # no hub, no npc, single quest -> weak
    v3_rows = _v3_rows({"cluster-stray": ["q-x1"]})
    _candidates, _families, decisions, selected = select_zone_arc_families(
        zone_id=ZONE_ID,
        cluster_summaries=clusters,
        v3_rows=v3_rows,
        quest_records=quest_records,
    )
    assert selected == []
    assert any(
        "single_quest_insufficient_signal" in decision["reason_codes"] for decision in decisions
    )


def test_arc_selection_artifact_rejects_duplicate_normalized_variant_labels() -> None:
    # Adversarial: two selected candidates that normalize to the same label must be rejected.
    candidate_a = ArcCandidate(
        candidate_id="arc-a",
        zone_id=ZONE_ID,
        component_ids=["c-a"],
        quest_node_ids=["q-a1"],
        base_title="The Sealed Gate",
        coherent_score=4.0,
    )
    candidate_b = ArcCandidate(
        candidate_id="arc-b",
        zone_id=ZONE_ID,
        component_ids=["c-b"],
        quest_node_ids=["q-b1"],
        base_title="The Sealed Gate",
        coherent_score=4.0,
    )
    family = ArcFamily(
        family_id="family-sealed-gate",
        zone_id=ZONE_ID,
        base_title="The Sealed Gate",
        candidate_ids=["arc-a", "arc-b"],
        coherent_score=4.0,
    )
    with pytest.raises(ValueError):
        QuestlineArcSelectionArtifact(
            candidates=[candidate_a, candidate_b],
            families=[family],
            decisions=[
                ArcFamilyDecision(
                    decision_id="arc-include-arc-a",
                    zone_id=ZONE_ID,
                    decision="include",
                    candidate_ids=["arc-a"],
                )
            ],
            selected_candidate_ids_by_zone={ZONE_ID: ["arc-a", "arc-b"]},
        )


# ---------------------------------------------------------------------------
# Behavior 7 — title idempotence
# ---------------------------------------------------------------------------


def test_structured_title_renders_variant_suffix_exactly_once() -> None:
    rendered = render_questline_title(
        {"base_title": "The Sealed Gate", "faction_variant": "alliance", "phase_variant": ""}
    )
    assert rendered == "The Sealed Gate (Alliance)"
    # Idempotent by construction: rendering the same structured fields again is stable and never
    # accumulates a second "(Alliance)" suffix.
    again = render_questline_title(
        {"base_title": "The Sealed Gate", "faction_variant": "alliance", "phase_variant": ""}
    )
    assert again == rendered
    assert rendered.count("(Alliance)") == 1


def test_title_render_keeps_base_title_free_of_decoration() -> None:
    # Adversarial: repeated variant decoration lives only in the structured fields; the base title
    # carries no suffix, so no doubled "(Alliance) (Alliance)" can be produced.
    rendered = render_questline_title(
        {"base_title": "Defense of the Vale", "faction_variant": "horde", "phase_variant": "Cataclysm"}
    )
    assert rendered == "Defense of the Vale (Horde) (Cataclysm)"
    assert rendered.count("(Horde)") == 1


# ---------------------------------------------------------------------------
# Behavior 8 — final CTA validity
# ---------------------------------------------------------------------------


def test_finalized_cta_is_a_single_complete_clause() -> None:
    finalized = finalize_cta_hook("Rally the wardens and secure the signal fire before nightfall.")
    assert lint_cta_hook(finalized) == []


def test_cta_lint_flags_malformed_and_truncated_clauses() -> None:
    # Adversarial: a dangling trailing function word.
    assert lint_cta_hook("Rally the wardens and secure the") != []
    # Adversarial: a dangling subordinating tail that should be treated as truncated.
    assert lint_cta_hook("Rally the wardens before.") != []
    # Adversarial: a malformed conjunction join.
    assert lint_cta_hook("Rally the wardens and and secure the fire.") != []
    # Adversarial: multiple sentences where one complete clause is required.
    assert lint_cta_hook("Rally the wardens. Secure the fire.") != []


def test_finalizer_repairs_a_dangling_tail_into_a_valid_clause() -> None:
    finalized = finalize_cta_hook("Rally the wardens and secure the signal fire and")
    assert lint_cta_hook(finalized) == []
