from __future__ import annotations

from pipeline.generate.draft import finalize_trace
from pipeline.generate.draft.faction_scoring import (
    MIN_SCORE,
    FactionCandidate,
    candidates_for_finalize,
    finalize_evidence_pools,
    score_faction_candidate,
)
from pipeline.generate.draft.pages.cards import _finalize_faction_card, build_major_factions
from pipeline.generate.draft.prose_synthesis import SYNTHESIS_MAX_ATTEMPTS


def test_finalize_evidence_pools_merges_seed_first_then_profile_identity() -> None:
    profile = [
        {
            "source_id": "src-profile",
            "snippet": "The Argent Crusade is a faction in Azeroth.",
            "section_role": "lead",
        },
        {
            "source_id": "src-profile-history",
            "snippet": "The Argent Crusade traces its origins to earlier anti-Scourge orders.",
            "section_role": "history",
        },
        {
            "source_id": "src-profile-intro",
            "snippet": "Argent Crusade knights organize campaigns against undead threats.",
            "section_role": "introduction",
        },
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
    pool = finalize_evidence_pools(candidate)
    assert pool == [seed[0], profile[0], profile[2]]


def test_finalize_faction_card_uses_one_merged_pool_offline(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    profile = [
        {
            "source_id": "src-profile",
            "snippet": "The Argent Crusade is a small faction in Azeroth.",
            "section_role": "lead",
        }
    ]
    seed = [
        {
            "source_id": "src-zone",
            "snippet": (
                "Argent Crusade patrols continue to push back undead forces along the main road "
                "while coordinating reclamation efforts across Example Zone throughout the frontier."
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
    card, used, pool = _finalize_faction_card(
        candidate,
        zone_name="Example Zone",
        subregion_tokens=[],
    )
    assert card is not None
    assert used == ["src-zone"]
    assert pool == [seed[0], profile[0]]
    assert "patrols" in str(card.get("summary", "")).lower()


def test_finalize_faction_card_retries_single_pool_with_full_budget(monkeypatch) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    calls: list[tuple[list[str], str]] = []
    candidate = FactionCandidate(
        faction_id="faction-argent-crusade",
        name="Argent Crusade",
        wiki_url="https://warcraft.wiki.gg/wiki/Argent_Crusade",
        profile_items=[
            {
                "source_id": "src-profile",
                "snippet": "Argent Crusade is an order formed to oppose undead threats.",
                "section_role": "lead",
            }
        ],
        seed_mentions=[
            {
                "source_id": "src-zone",
                "snippet": (
                    "Argent Crusade patrols guard Example Zone roads and support reclamation "
                    "work against undead threats."
                ),
                "section_role": "quests_edit",
            }
        ],
    )

    def fake_synthesize(pool: list[dict], **kwargs: object) -> tuple[str, list[str]]:
        calls.append(([str(item["source_id"]) for item in pool], str(kwargs.get("reinforce", ""))))
        if len(calls) < SYNTHESIS_MAX_ATTEMPTS:
            return "Bad summary.", []
        return (
            "Argent Crusade patrols guard Example Zone roads against undead threats.",
            ["src-zone"],
        )

    monkeypatch.setattr("pipeline.generate.draft.pages.cards.llm_synthesis_active", lambda: True)
    monkeypatch.setattr("pipeline.generate.draft.pages.cards.passthrough_corpus", lambda pool: None)
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.cards.synthesize_faction_summary",
        fake_synthesize,
    )
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.cards.lint_faction_summary",
        lambda summary, **_: ["too short"] if summary == "Bad summary." else [],
    )
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.cards.prose_gate_violations",
        lambda *_args, **_kwargs: [],
    )

    card, used, pool = _finalize_faction_card(
        candidate,
        zone_name="Example Zone",
        subregion_tokens=[],
    )

    assert card is not None
    assert used == ["src-zone"]
    assert pool == finalize_evidence_pools(candidate)
    assert len(calls) == SYNTHESIS_MAX_ATTEMPTS
    assert all(source_ids == ["src-zone", "src-profile"] for source_ids, _ in calls)
    assert calls[1][1]


def test_finalize_faction_card_drop_trace_includes_rejected_text_and_reasons(
    monkeypatch,
) -> None:
    monkeypatch.delenv("WOW_LORE_WIKI_FIRST_NO_LLM", raising=False)
    candidate = FactionCandidate(
        faction_id="faction-alliance",
        name="Alliance",
        wiki_url="https://warcraft.wiki.gg/wiki/Alliance",
        seed_mentions=[
            {
                "source_id": "src-zone",
                "snippet": "Alliance forces advance through Example Zone during the campaign.",
                "section_role": "quests_edit",
            }
        ],
    )
    attempt = 0

    def fake_synthesize(_pool: list[dict], **_kwargs: object) -> tuple[str, list[str]]:
        nonlocal attempt
        attempt += 1
        return f"Rejected summary {attempt}.", ["src-zone"]

    monkeypatch.setattr("pipeline.generate.draft.pages.cards.llm_synthesis_active", lambda: True)
    monkeypatch.setattr("pipeline.generate.draft.pages.cards.passthrough_corpus", lambda pool: None)
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.cards.synthesize_faction_summary",
        fake_synthesize,
    )
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.cards.lint_faction_summary",
        lambda *_args, **_kwargs: ["lacks zone role framing", "too short"],
    )
    monkeypatch.setattr(
        "pipeline.generate.draft.pages.cards.prose_gate_violations",
        lambda *_args, **_kwargs: ["generic non-answer"],
    )

    finalize_trace.begin("zone-example")
    card, _, _ = _finalize_faction_card(
        candidate,
        zone_name="Example Zone",
        subregion_tokens=[],
    )
    records = finalize_trace.drain()

    assert card is None
    drop = next(record for record in records if record["stage"] == "major_factions.finalize")
    assert drop["entity_id"] == "zone-example"
    assert drop["faction_id"] == "faction-alliance"
    assert drop["rejected_summary"] == f"Rejected summary {SYNTHESIS_MAX_ATTEMPTS}."
    assert drop["reasons"] == [
        "lacks zone role framing",
        "too short",
        "generic non-answer",
    ]
    assert drop["attempts"] == SYNTHESIS_MAX_ATTEMPTS


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


def test_subzone_named_summary_elects_only_with_location_anchor_tokens(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    # A faction whose only synthesizable involvement is framed around a subzone ("the battle for
    # Andorhal") and never names the zone verbatim. With no maps/subregion section in the evidence,
    # extract_subregion_tokens is empty and the anchor lint effectively demands the literal zone
    # name, silently dropping the card even though it ranks. Passing the zone's elected location-card
    # names as extra anchors (its real subzones) rescues it.
    role_pool = [
        {
            "source_id": "src-zone",
            "snippet": (
                "The Argent Crusade still guards the reclaimed farms around Andorhal, having broken "
                "the Scourge's grip there during the long battle for the town and driven the cauldron "
                "lords from the poisoned fields."
            ),
            "section_role": "quests_edit",
        }
    ]
    targets = [
        {
            "zone_id": "zone-x",
            "faction_id": "faction-argent-crusade",
            "name": "Argent Crusade",
            "source_link": "",
        }
    ]
    common = dict(
        zone_id="zone-x",
        zone_name="Example Zone",
        evidence_rows=[],
        pools={"faction_role_pool": role_pool, "faction_pool": []},
        questline_rows=[],
        revision_map={"src-zone": "mw:1"},
        faction_profile_targets=targets,
    )
    cards_without, _ = build_major_factions(**common)
    assert not any(card["id"] == "faction-argent-crusade" for card in cards_without)

    cards_with, provenance = build_major_factions(**common, extra_subregion_tokens=["Andorhal"])
    assert any(card["id"] == "faction-argent-crusade" for card in cards_with)
    assert provenance.get("faction-argent-crusade"), "rescued card must carry a provenance pointer"


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
