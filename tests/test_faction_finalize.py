from __future__ import annotations

import os

from pipeline.generate.draft.faction_scoring import (
    FactionCandidate,
    MIN_SCORE,
    candidates_for_finalize,
    finalize_evidence_pools,
    score_faction_candidate,
)
from pipeline.generate.draft.wiki_first import _finalize_faction_card


def test_finalize_evidence_pools_tries_seed_after_profile() -> None:
    profile = [{"source_id": "src-profile", "snippet": "The Argent Crusade is a faction in Azeroth.", "section_role": "lead"}]
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
