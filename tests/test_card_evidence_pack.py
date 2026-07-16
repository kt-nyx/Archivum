"""Slice 7: per-card evidence packs and claim-level grounding.

Synthetic, generic fixtures only — invented place/actor names, never pilot output. Each test names
the Slice 7 behavior it pins.
"""

from __future__ import annotations

import pytest

from pipeline.contracts.models import (
    CardEvidencePackArtifact,
    CardEvidencePackSufficiency,
    CardEvidenceRole,
)
from pipeline.generate.draft.card_evidence_pack import (
    CARD_EVIDENCE_PACK_SCHEMA_VERSION,
    build_card_evidence_pack,
    build_card_evidence_pack_artifact,
    load_card_evidence_pack_artifact,
    pack_is_sufficient,
)


def _item(
    *,
    snippet: str,
    canonical_evidence_id: str = "",
    source_id: str = "",
    owner: str = "",
    claim_views: list[dict] | None = None,
) -> dict:
    item: dict = {"snippet": snippet}
    if canonical_evidence_id:
        item["canonical_evidence_id"] = canonical_evidence_id
    if source_id:
        item["source_id"] = source_id
    if owner:
        item["location_id"] = owner
    if claim_views is not None:
        item["_claim_views"] = claim_views
    return item


# --- required behavior: selected subject whose only evidence is a foreign-page mention is dropped --


def test_mention_only_subject_yields_insufficient_pack() -> None:
    # A place whose only evidence is a mention on another page (owned by that page) has no direct
    # identity evidence: the pack is insufficient, so the card is dropped rather than described from
    # a borrowed paragraph.
    pack = build_card_evidence_pack(
        card_id="loc-hidden-glade",
        card_type="location",
        subject_id="loc-hidden-glade",
        subject_name="Hidden Glade",
        identity_items=[],
        relationship_items=[
            _item(
                snippet="The Verdant March oversees the Hidden Glade at its northern edge.",
                canonical_evidence_id="c-march-1",
                source_id="src-verdant-march",
                owner="loc-verdant-march",
            )
        ],
    )
    assert not pack_is_sufficient(pack)
    assert pack.sufficiency == CardEvidencePackSufficiency.INSUFFICIENT_IDENTITY_EVIDENCE
    assert pack.identity_evidence == []
    assert pack.provenance_ids == []


# --- required behavior: containment-direction is preserved on relationship evidence ----------------


def test_relationship_evidence_preserves_owner_and_direction() -> None:
    # The child place is directly evidenced on its own page (identity); the parent-page mention is
    # relationship evidence whose recorded direction reads parent --mentions--> child, never
    # inverted into the child owning the parent's paragraph.
    pack = build_card_evidence_pack(
        card_id="loc-karn-hollow",
        card_type="location",
        subject_id="loc-karn-hollow",
        subject_name="Karn Hollow",
        identity_items=[
            _item(
                snippet="Karn Hollow is a mining camp carved into the eastern cliffs.",
                canonical_evidence_id="c-hollow-1",
                source_id="src-karn-hollow",
            )
        ],
        relationship_items=[
            _item(
                snippet="The Ashen Reach contains Karn Hollow among its border camps.",
                canonical_evidence_id="c-reach-1",
                source_id="src-ashen-reach",
                owner="loc-ashen-reach",
            )
        ],
    )
    assert pack_is_sufficient(pack)
    assert [ref.role for ref in pack.identity_evidence] == [CardEvidenceRole.IDENTITY]
    assert len(pack.relationship_evidence) == 1
    relation = pack.relationship_evidence[0]
    assert relation.role == CardEvidenceRole.RELATIONSHIP
    assert relation.owner_subject_id == "loc-ashen-reach"
    assert relation.direction == "mentions_subject"
    # The parent-owned paragraph never becomes the child's identity evidence.
    assert all(ref.evidence_id != "c-reach-1" for ref in pack.identity_evidence)


# --- required behavior: provenance resolves to the card's own identity source ---------------------


def test_provenance_ids_are_identity_paragraphs_only() -> None:
    pack = build_card_evidence_pack(
        card_id="loc-karn-hollow",
        card_type="location",
        subject_id="loc-karn-hollow",
        subject_name="Karn Hollow",
        identity_items=[
            _item(snippet="Karn Hollow guards the pass.", canonical_evidence_id="c-hollow-1"),
            _item(snippet="Karn Hollow was founded long ago.", canonical_evidence_id="c-hollow-2"),
        ],
        relationship_items=[
            _item(
                snippet="The Ashen Reach contains Karn Hollow.",
                canonical_evidence_id="c-reach-1",
                owner="loc-ashen-reach",
            )
        ],
    )
    assert pack.provenance_ids == ["c-hollow-1", "c-hollow-2"]
    assert "c-reach-1" not in pack.provenance_ids


# --- required behavior: compound assertion split/rejected when one clause lacks support -----------


def test_compound_claim_drops_unsupported_clause() -> None:
    pack = build_card_evidence_pack(
        card_id="loc-redstone-keep",
        card_type="location",
        subject_id="loc-redstone-keep",
        subject_name="Redstone Keep",
        identity_items=[
            _item(
                snippet="ignored",
                canonical_evidence_id="c-keep-1",
                claim_views=[
                    {
                        "claim_id": "cl-1",
                        "canonical_evidence_id": "c-keep-1",
                        "claim_text": (
                            "Redstone Keep held the pass and Vexthar razed the fields"
                        ),
                    }
                ],
            )
        ],
    )
    assert pack_is_sufficient(pack)
    assert len(pack.claim_views) == 1
    view = pack.claim_views[0]
    assert view.claim_text == "Redstone Keep held the pass"
    assert "Vexthar razed the fields" in view.dropped_clauses


def test_claim_about_other_subject_is_rejected() -> None:
    pack = build_card_evidence_pack(
        card_id="loc-redstone-keep",
        card_type="location",
        subject_id="loc-redstone-keep",
        subject_name="Redstone Keep",
        identity_items=[
            _item(
                snippet="ignored",
                canonical_evidence_id="c-keep-1",
                claim_views=[
                    {
                        "claim_id": "cl-1",
                        "canonical_evidence_id": "c-keep-1",
                        "claim_text": "Vexthar razed the fields",
                    }
                ],
            )
        ],
    )
    # Identity paragraph still grounds the pack, but the unsupported claim never becomes a view.
    assert pack_is_sufficient(pack)
    assert pack.claim_views == []


# --- required behavior: unselected crawl data incurs no claim-extraction work ---------------------


def test_claim_extractor_runs_only_on_identity_items() -> None:
    calls: list[str] = []

    def _spy_extractor(item: dict) -> list[dict]:
        calls.append(str(item.get("canonical_evidence_id", "")))
        return [
            {
                "claim_id": "",
                "claim_text": str(item.get("snippet", "")),
                "evidence_id": str(item.get("canonical_evidence_id", "")),
            }
        ]

    identity = [
        _item(snippet="Karn Hollow guards the pass.", canonical_evidence_id="c-hollow-1"),
        _item(snippet="Karn Hollow was founded long ago.", canonical_evidence_id="c-hollow-2"),
    ]
    relationship = [
        _item(
            snippet="The Ashen Reach contains Karn Hollow.",
            canonical_evidence_id="c-reach-1",
            owner="loc-ashen-reach",
        )
    ]
    build_card_evidence_pack(
        card_id="loc-karn-hollow",
        card_type="location",
        subject_id="loc-karn-hollow",
        subject_name="Karn Hollow",
        identity_items=identity,
        relationship_items=relationship,
        claim_extractor=_spy_extractor,
    )
    # Exactly the selected card's identity paragraphs are extracted; the relationship paragraph and
    # every unselected crawl paragraph are never handed to claim extraction.
    assert calls == ["c-hollow-1", "c-hollow-2"]
    assert "c-reach-1" not in calls


# --- adversarial / edge cases --------------------------------------------------------------------


def test_item_without_any_id_is_not_identity() -> None:
    pack = build_card_evidence_pack(
        card_id="loc-x",
        card_type="location",
        subject_id="loc-x",
        subject_name="Placeholder",
        identity_items=[_item(snippet="A paragraph with no citable id.")],
    )
    assert not pack_is_sufficient(pack)


def test_malformed_empty_claim_is_ignored() -> None:
    pack = build_card_evidence_pack(
        card_id="loc-keep",
        card_type="location",
        subject_id="loc-keep",
        subject_name="Redstone Keep",
        identity_items=[
            _item(
                snippet="Redstone Keep stands.",
                canonical_evidence_id="c-keep-1",
                claim_views=[{"claim_id": "cl", "canonical_evidence_id": "c-keep-1", "claim_text": ""}],
            )
        ],
    )
    # Identity still holds; the empty claim yields no view (falls back to the snippet claim).
    assert pack_is_sufficient(pack)
    assert all(view.claim_text for view in pack.claim_views)


def test_empty_subject_name_admits_whole_claim() -> None:
    # A questline arc has structural (cluster) identity rather than a name in prose, so the
    # name-based compound check is skipped and cluster paragraphs are admitted whole.
    pack = build_card_evidence_pack(
        card_id="ql-cluster-a",
        card_type="questline",
        subject_id="cluster-a",
        subject_name="",
        identity_items=[
            _item(snippet="Rescue the scouts and then torch the siege works.", source_id="src-q1")
        ],
    )
    assert pack_is_sufficient(pack)
    assert [view.claim_text for view in pack.claim_views] == [
        "Rescue the scouts and then torch the siege works."
    ]


# --- versioned, fail-fast artifact ---------------------------------------------------------------


def test_artifact_round_trips_current_version() -> None:
    pack = build_card_evidence_pack(
        card_id="loc-keep",
        card_type="location",
        subject_id="loc-keep",
        subject_name="Redstone Keep",
        identity_items=[_item(snippet="Redstone Keep stands.", canonical_evidence_id="c-keep-1")],
    )
    payload = build_card_evidence_pack_artifact([pack])
    assert payload["schema_version"] == CARD_EVIDENCE_PACK_SCHEMA_VERSION
    loaded = load_card_evidence_pack_artifact(payload)
    assert isinstance(loaded, CardEvidencePackArtifact)
    assert loaded.decisions[0].card_id == "loc-keep"


def test_loader_rejects_missing_or_wrong_version() -> None:
    with pytest.raises(ValueError, match="card_evidence_pack.v1"):
        load_card_evidence_pack_artifact({"producer": "draft_writer", "decisions": []})
    with pytest.raises(ValueError, match="card_evidence_pack.v1"):
        load_card_evidence_pack_artifact({"schema_version": "card_evidence_pack.v0", "decisions": []})


# --- producer wiring: a rendered faction card yields a sufficient pack in the sink ----------------


def test_build_major_factions_populates_pack_sink(monkeypatch) -> None:
    from pipeline.contracts.models import CardEvidencePackDecision
    from pipeline.generate.draft.pages.cards import build_major_factions

    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    role_pool = [
        {
            "source_id": "src-good",
            "snippet": (
                "The Ashen Order continues to hold the crypts beneath Example Zone, raising the "
                "dead and guarding the ruins against every intruder along the frozen frontier."
            ),
            "section_role": "lore_history",
            "content_role": "lore_history",
        },
        {
            "source_id": "src-good-2",
            "snippet": "The Ashen Order still occupies Example Zone in great numbers.",
            "section_role": "lore_history",
            "content_role": "lore_history",
        },
    ]
    targets = [
        {
            "zone_id": "instance-x",
            "faction_id": "faction-ashen-order",
            "name": "Ashen Order",
            "source_link": "",
        }
    ]
    packs: list[CardEvidencePackDecision] = []
    cards, provenance = build_major_factions(
        zone_id="instance-x",
        zone_name="Example Zone",
        evidence_rows=[],
        pools={"faction_role_pool": role_pool, "faction_pool": []},
        questline_rows=[],
        revision_map={"src-good": "mw:1", "src-good-2": "mw:2"},
        faction_profile_targets=targets,
        pack_sink=packs,
    )
    assert any(card["id"] == "faction-ashen-order" for card in cards)
    pack = next(p for p in packs if p.card_id == "faction-ashen-order")
    assert pack_is_sufficient(pack)
    assert pack.card_type == "faction"
    assert pack.provenance_ids  # resolves to the faction's own subject-naming evidence
    assert provenance.get("faction-ashen-order")
