from __future__ import annotations

from pipeline.generate.draft.faction_scoring import (
    MIN_SCORE,
    FactionCandidate,
    candidates_for_finalize,
    finalize_evidence_pools,
    score_faction_candidate,
)
from pipeline.generate.draft.pages.cards import _finalize_faction_card, build_major_factions


def test_finalize_evidence_pools_tries_seed_after_profile() -> None:
    profile = [
        {
            "source_id": "src-profile",
            "snippet": "The Argent Crusade is a faction in Azeroth.",
            "section_role": "lead",
        }
    ]
    seed = [
        {
            "source_id": "src-zone",
            "snippet": (
                "Argent Crusade patrols continue to push back undead forces along the main road "
                "while coordinating reclamation efforts across the contested frontier."
            ),
            "section_role": "quests_edit",
        }
    ]
    candidate = FactionCandidate(
        faction_id="faction-argent-crusade",
        name="Argent Crusade",
        wiki_url="https://warcraft.wiki.gg/wiki/Argent_Crusade",
        profile_items=profile,
        seed_mentions=seed,
    )
    pools = finalize_evidence_pools(candidate)
    assert len(pools) == 2
    assert pools[0] == profile
    assert pools[1] == seed


def test_finalize_faction_card_rescues_from_seed_when_profile_fails_lint(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    candidate = FactionCandidate(
        faction_id="faction-argent-crusade",
        name="Argent Crusade",
        wiki_url="https://warcraft.wiki.gg/wiki/Argent_Crusade",
        profile_items=[
            {
                "source_id": "src-profile",
                "snippet": "The Argent Crusade is a small faction in Azeroth.",
                "section_role": "lead",
            }
        ],
        seed_mentions=[
            {
                "source_id": "src-zone",
                "snippet": (
                    "Argent Crusade patrols continue to push back undead forces along the main road "
                    "while coordinating reclamation efforts across Example Zone throughout the frontier."
                ),
                "section_role": "quests_edit",
            }
        ],
    )
    card, used, pool = _finalize_faction_card(
        candidate,
        zone_name="Example Zone",
        subregion_tokens=[],
    )
    assert card is not None
    assert used == ["src-zone"]
    assert pool == candidate.seed_mentions
    assert "patrols" in str(card.get("summary", "")).lower()


def test_build_major_factions_provenance_falls_back_to_resolvable_pool_source(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    # The deterministic fallback summary borrows the longest zone-anchored snippet, which here
    # comes from a related-lore source absent from revision_map. A second, resolvable source is
    # also in the pool. The emitted card must still carry a provenance pointer (the release gate
    # hard-fails on provenance.missing_card_pointers without one).
    role_pool = [
        {
            "source_id": "src-unresolvable",
            "snippet": (
                "Scourge legions continue to hold the crypts beneath Example Zone, raising the "
                "dead and guarding the ruins against every intruder along the frozen frontier."
            ),
            "section_role": "lore_history",
            "content_role": "lore_history",
        },
        {
            "source_id": "src-good",
            "snippet": "The Scourge still occupies Example Zone in great numbers.",
            "section_role": "lore_history",
            "content_role": "lore_history",
        },
    ]
    targets = [
        {"zone_id": "instance-x", "faction_id": "faction-scourge", "name": "Scourge", "source_link": ""}
    ]
    cards, provenance = build_major_factions(
        zone_id="instance-x",
        zone_name="Example Zone",
        evidence_rows=[],
        pools={"faction_role_pool": role_pool, "faction_pool": []},
        questline_rows=[],
        revision_map={"src-good": "mw:1"},  # src-unresolvable deliberately absent
        faction_profile_targets=targets,
    )
    assert any(card["id"] == "faction-scourge" for card in cards)
    pointers = provenance.get("faction-scourge")
    assert pointers, "emitted faction card must carry >=1 provenance pointer"
    # The unresolvable picked source is skipped; the pointer resolves to the in-map source.
    assert all(pointer["source_id"] == "src-good" for pointer in pointers)


def test_candidates_for_finalize_keeps_sub_threshold_out_when_eligible_exist() -> None:
    strong = FactionCandidate(
        faction_id="faction-argent-crusade",
        name="Argent Crusade",
        wiki_url="https://example.test/argent",
        profile_items=[{"source_id": "a", "snippet": "x" * 80, "section_role": "history"}],
        seed_mentions=[
            {
                "source_id": "a",
                "snippet": "Argent Crusade patrols continue to push back undead forces along the main road.",
                "section_role": "quests_edit",
            }
        ],
    )
    weak = FactionCandidate(
        faction_id="faction-minor-order",
        name="Minor Order",
        wiki_url="https://example.test/minor",
        seed_mentions=[
            {
                "source_id": "b",
                "snippet": "Minor Order scouts watch the border near the outpost each night.",
                "section_role": "history",
                "field_name": "history_digest",
            }
        ],
    )
    scored_strong = score_faction_candidate(strong)
    scored_weak = score_faction_candidate(weak)
    assert scored_strong.score >= MIN_SCORE
    assert 0 < scored_weak.score < MIN_SCORE

    _, queue = candidates_for_finalize([strong, weak])
    queue_ids = {row.faction_id for row in queue}
    assert "faction-argent-crusade" in queue_ids
    assert "faction-minor-order" not in queue_ids
