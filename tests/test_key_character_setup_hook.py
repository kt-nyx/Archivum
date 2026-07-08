from __future__ import annotations

from pipeline.generate.draft.claim_routing import CLAIM_VIEW_KEY
from pipeline.generate.draft.pages.key_characters import (
    _beat_is_self_motivation,
    _key_character_summary_pool,
    _recover_instance_setup_hooks,
)
from pipeline.generate.draft.prose_synthesis import KEY_CHARACTER_EVIDENCE_ITEM_LIMIT
from pipeline.generate.draft.temporal import PRE_ENTRY_HISTORY, SAFE_BACKGROUND

_CAST = ["Darkmaster Gandling", "Instructor Chillheart", "Jandice Barov", "Rattlegore"]


def test_beat_is_self_motivation_keeps_self_agent_aim() -> None:
    # The card character is the grammatical agent and no other cast member is named.
    assert _beat_is_self_motivation(
        "Lilian Voss turned her wrath on the Scourge necromancers of Scholomance.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def test_beat_is_self_motivation_drops_character_as_patient() -> None:
    # An in-encounter mechanic: another cast member acts upon the card character.
    assert not _beat_is_self_motivation(
        "Darkmaster Gandling forced Lilian Voss to fight the adventurers.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def test_beat_is_self_motivation_drops_other_cast_named_even_at_sentence_end() -> None:
    # A cast member named anywhere disqualifies — including at a clause/sentence boundary, where a
    # trailing period must not hide the name from the token match.
    assert not _beat_is_self_motivation(
        "Lilian Voss caught up with Darkmaster Gandling.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def test_beat_is_self_motivation_drops_outcome_where_character_is_freed() -> None:
    assert not _beat_is_self_motivation(
        "The adventurers defeated and freed Lilian Voss.",
        self_name="Lilian Voss",
        other_cast_names=_CAST,
    )


def _hook_view(text: str, *, safety: str = "safe_setup_hook") -> dict:
    return {
        "is_claim_view": True,
        "spoiler_safety": safety,
        "claim_text": text,
        "snippet": text,
        "claim_id": text[:12],
        "entities": [],
        "canonical_evidence_id": f"canon-{abs(hash(text)) % 99999}",
    }


def _item(views: list[dict]) -> dict:
    return {CLAIM_VIEW_KEY: views}


def test_recover_instance_setup_hooks_recovers_only_the_motivation() -> None:
    pool = [
        _item(
            [
                _hook_view(
                    "Lilian Voss turned her wrath on the Scourge necromancers of Scholomance."
                ),
                _hook_view(
                    "Darkmaster Gandling forced Lilian Voss to fight the adventurers in Scholomance."
                ),
            ]
        )
    ]
    recovered = _recover_instance_setup_hooks(
        pool,
        instance_name="Scholomance",
        boss_name="Lilian Voss",
        other_cast_names=["Darkmaster Gandling"],
        selected=[],
    )
    texts = [str(v.get("claim_text", "")) for v in recovered]
    assert any("turned her wrath" in t for t in texts)
    assert not any("forced" in t for t in texts)
    # The recovered hook is detached from its source paragraph so synthesis keeps its text.
    assert all(v.get("canonical_evidence_id") == "" for v in recovered)


def test_recover_instance_setup_hooks_noop_when_instance_beat_already_selected() -> None:
    pool = [
        _item(
            [_hook_view("Lilian Voss turned her wrath on the necromancers of Scholomance.")]
        )
    ]
    selected = [
        {
            "is_claim_view": True,
            "claim_text": "Her story is bound to Scholomance.",
            "snippet": "Her story is bound to Scholomance.",
            "entities": [],
        }
    ]
    recovered = _recover_instance_setup_hooks(
        pool,
        instance_name="Scholomance",
        boss_name="Lilian Voss",
        other_cast_names=["Darkmaster Gandling"],
        selected=selected,
    )
    assert recovered == []


def test_recovered_hook_is_pinned_within_evidence_window(monkeypatch) -> None:
    # Even when the background selection fills the evidence window, the recovered motivation hook
    # survives (it is not truncated by the synthesis item cap) and the pool stays within budget.
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")

    def _bg(i: int) -> dict:
        text = f"Background fact number {i} about the character's early life."
        return {
            "is_claim_view": True,
            "temporal_scope": PRE_ENTRY_HISTORY,
            "spoiler_safety": SAFE_BACKGROUND,
            "claim_text": text,
            "snippet": text,
            "claim_id": f"bg{i}",
            "canonical_evidence_id": f"canon-bg-{i}",
            "entities": [],
        }

    bg_item = {CLAIM_VIEW_KEY: [_bg(i) for i in range(KEY_CHARACTER_EVIDENCE_ITEM_LIMIT + 8)]}
    hook_item = {
        CLAIM_VIEW_KEY: [
            {
                "is_claim_view": True,
                "temporal_scope": "active_storyline",
                "spoiler_safety": "safe_setup_hook",
                "claim_text": (
                    "Lilian Voss turned her wrath on the Scourge necromancers of Scholomance."
                ),
                "snippet": (
                    "Lilian Voss turned her wrath on the Scourge necromancers of Scholomance."
                ),
                "claim_id": "hook0",
                "canonical_evidence_id": "canon-hook",
                "entities": [],
            }
        ]
    }

    ordered = _key_character_summary_pool(
        [bg_item, hook_item],
        instance_name="Scholomance",
        boss_name="Lilian Voss",
        other_cast_names=["Darkmaster Gandling"],
    )
    texts = [str(v.get("claim_text", "")) for v in ordered]
    assert any("turned her wrath" in t for t in texts)
    assert len(ordered) <= KEY_CHARACTER_EVIDENCE_ITEM_LIMIT
