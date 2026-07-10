"""Behavioral tests for Slice 1's evidence-based card-admission contract."""

from __future__ import annotations

from pipeline.contracts.models import EntityKind
from pipeline.discovery.entity_typing import decide_entity_kind


def _decision(title: str, *, categories: list[str] | None = None, infobox: dict[str, str] | None = None):
    return decide_entity_kind(
        candidate_id="entity-example",
        canonical_title=title,
        canonical_path="/wiki/Example",
        source_snapshot={
            "source_id": "src-target",
            "categories": categories or [],
            "infobox": infobox or {},
        },
        source_relation="maps_subregions",
        source_ids=["src-zone"],
    )


def test_target_page_taxonomy_resolves_the_closed_output_enum() -> None:
    assert _decision("Example Race", categories=["Playable races"]).kind == EntityKind.GROUP_OR_SPECIES
    assert _decision("Example Ability", categories=["Combat abilities"]).kind == EntityKind.OBJECT_OR_CONCEPT
    assert _decision("Example Actor", categories=["Lore characters"]).kind == EntityKind.NAMED_ACTOR
    assert _decision("Example Place", categories=["Example Zone subzones"]).kind == EntityKind.PLACE


def test_untyped_link_abstains_even_when_its_source_relationship_is_geographic() -> None:
    decision = _decision("Capitalized Proper Noun")
    assert decision.kind == EntityKind.UNKNOWN
    assert decision.reason_codes == ["insufficient_target_evidence"]
    assert "source_relation:maps_subregions" in decision.source_signals


def test_conflicting_target_signals_abstain_instead_of_picking_a_title_based_default() -> None:
    decision = _decision(
        "Ambiguous Target",
        categories=["Example Zone subzones", "Playable races"],
    )
    assert decision.kind == EntityKind.UNKNOWN
    assert decision.reason_codes == ["conflicting_target_evidence"]


def test_infobox_is_affirmative_target_evidence() -> None:
    decision = _decision("Unknown Name", infobox={"Entity type": "organization"})
    assert decision.kind == EntityKind.ORGANIZATION
    assert "infobox:organization" in decision.source_signals
